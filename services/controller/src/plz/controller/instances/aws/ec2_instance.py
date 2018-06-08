import io
import logging
import os.path
import time
from typing import Dict, Iterator, List, Optional

from redis import StrictRedis

from plz.controller.containers import ContainerState, Containers
from plz.controller.images import Images
from plz.controller.instances.docker import DockerInstance
from plz.controller.instances.instance_base \
    import ExecutionInfo, Instance, Parameters
from plz.controller.results import ResultsStorage
from plz.controller.volumes import Volumes

log = logging.getLogger(__name__)


class EC2Instance(Instance):
    ROOT = os.path.join(os.path.dirname(__file__), '..', '..', '..')

    # We find available instances by looking at those in which
    # the Execution-Id tag is the empty string. Instances are
    # started with an empty value for this tag, the tag is set
    # when the instance starts executing, and it's emptied again
    # when the execution finishes
    EXECUTION_ID_TAG = 'Plz:Execution-Id'
    GROUP_NAME_TAG = 'Plz:Group-Id'
    MAX_IDLE_SECONDS_TAG = 'Plz:Max-Idle-Seconds'
    IDLE_SINCE_TIMESTAMP_TAG = 'Plz:Idle-Since-Timestamp'

    def __init__(self,
                 client,
                 images: Images,
                 containers: Containers,
                 volumes: Volumes,
                 container_execution_id: str,
                 data: dict,
                 redis: StrictRedis):
        super().__init__(redis)
        self.client = client
        self.images = images
        self.delegate = DockerInstance(
            images, containers, volumes, container_execution_id, redis)
        self.data = data

    def run(self,
            command: List[str],
            snapshot_id: str,
            parameters: Parameters,
            input_stream: Optional[io.BytesIO],
            docker_run_args: Dict[str, str],
            max_idle_seconds: int = 60 * 30) -> None:
        with self._lock:
            if not self._is_running_and_free():
                raise InstanceAssignedException(
                    f'Instance {self._instance_id} cannot execute '
                    f'{self.delegate.execution_id} as it\'s not '
                    f'free (executing [{self.get_execution_id()}])')
            self.images.pull(snapshot_id)
            self.delegate.run(command, snapshot_id, parameters, input_stream,
                              docker_run_args)
            self._set_execution_id(
                self.delegate.execution_id, max_idle_seconds)

    def is_up(self, is_instance_newly_created: bool):
        if not self._is_running():
            return False
        return self.images.can_pull(
            5 if is_instance_newly_created else 1)

    def _dispose(self):
        self.client.terminate_instances(InstanceIds=[self._instance_id])

    def _set_execution_id(
            self, execution_id: str, max_idle_seconds: int):
        self._set_tags([
            {'Key': EC2Instance.EXECUTION_ID_TAG,
             'Value': execution_id},
            {'Key': EC2Instance.MAX_IDLE_SECONDS_TAG,
             'Value': str(max_idle_seconds)}
        ])

    def _set_tags(self, tags):
        instance_id = self._instance_id
        self.client.create_tags(Resources=[instance_id], Tags=tags)
        self.data = _describe_instances(
            self.client, [('instance-id', instance_id)])[0]

    def get_max_idle_seconds(self) -> int:
        return int(get_tag(
            self.data, self.MAX_IDLE_SECONDS_TAG, '0'))

    def get_idle_since_timestamp(
            self, container_state: Optional[ContainerState] = None) -> int:
        if container_state is not None:
            return container_state.finished_at
        return int(get_tag(
            self.data, self.IDLE_SINCE_TIMESTAMP_TAG, '0'))

    def get_execution_id(self):
        return get_tag(
            self.data, self.EXECUTION_ID_TAG, '')

    def get_instance_type(self):
        return self.data['InstanceType']

    def dispose_if_its_time(
            self, execution_info: Optional[ExecutionInfo] = None):
        if execution_info is not None:
            ei = execution_info
        else:
            ei = self.get_execution_info()

        now = int(time.time())
        # In weird cases just dispose as well
        if now - ei.idle_since_timestamp > ei.max_idle_seconds or \
                ei.idle_since_timestamp > now or \
                ei.max_idle_seconds <= 0:
            log.info(f'Disposing of instance {self._instance_id}')
            self._dispose()

    def stop_execution(self):
        return self.delegate.stop_execution()

    def container_state(self) -> Optional[ContainerState]:
        return self.delegate.container_state()

    def release(self,
                results_storage: ResultsStorage,
                idle_since_timestamp: int,
                release_container: bool = True):
        with self._lock:
            self.delegate.release(
                results_storage, idle_since_timestamp, release_container)
            self._set_tags([
                {'Key': EC2Instance.EXECUTION_ID_TAG,
                 'Value': ''},
                {'Key': EC2Instance.IDLE_SINCE_TIMESTAMP_TAG,
                 'Value': str(idle_since_timestamp)}])

    def _is_running_and_free(self):
        if not self._is_running():
            return False
        instances = get_aws_instances(
            self.client,
            only_running=True,
            filters=[(f'tag:{EC2Instance.EXECUTION_ID_TAG}', ''),
                     ('instance-id', self._instance_id)])
        return len(instances) > 0

    def _is_running(self):
        instances = get_aws_instances(
            self.client,
            only_running=True,
            filters=[('instance-id', self._instance_id)])
        return len(instances) > 0

    def get_resource_state(self) -> str:
        instance = _describe_instances(
            self.client,
            filters=[('instance-id', self._instance_id)])[0]
        return instance['State']['Name']

    def delete_resource(self) -> None:
        # It seems AWS doesn't allow to delete an instance. We set the group
        # tag to empty so it won't be listed for a group anymore.
        self._set_tags([{'Key': EC2Instance.GROUP_NAME_TAG,
                         'Value': ''}])

    def get_forensics(self) -> dict:
        spot_requests = self.client.describe_spot_instance_requests(
            Filters=[{'Name': 'instance-id',
                      'Values': [self._instance_id]}])['SpotInstanceRequests']
        if len(spot_requests) == 0:
            return {}
        if len(spot_requests) > 1:
            log.warning('More than one spot request for instance '
                        f'{self._instance_id}')
        return {'SpotInstanceRequest': spot_requests[0],
                'InstanceState': self.get_resource_state()}

    @property
    def _instance_id(self):
        return self.data['InstanceId']

    def get_logs(self, since: Optional[int] = None, stdout: bool = True,
                 stderr: bool = True) -> Iterator[bytes]:
        return self.delegate.get_logs(
            since=since, stdout=stdout, stderr=stderr)

    def get_output_files_tarball(self) -> Iterator[bytes]:
        return self.delegate.get_output_files_tarball()

    def get_measures_files_tarball(self) -> Iterator[bytes]:
        return self.delegate.get_measures_files_tarball()

    def get_stored_metadata(self) -> dict:
        return self.delegate.get_stored_metadata()


def get_tag(instance_data, tag, default=None) -> Optional[str]:
    for t in instance_data['Tags']:
        if t['Key'] == tag:
            return t['Value']
    return default


def get_aws_instances(
        client, filters: [(str, str)], only_running: bool) -> [dict]:
    if only_running:
        filters += [('instance-state-name', 'running')]
    return _describe_instances(client, filters)


def _describe_instances(client, filters) -> [dict]:
    new_filters = [{'Name': n, 'Values': [v]} for (n, v) in filters]
    response = client.describe_instances(Filters=new_filters)
    return [instance
            for reservation in response['Reservations']
            for instance in reservation['Instances']]


class InstanceAssignedException(Exception):
    pass
