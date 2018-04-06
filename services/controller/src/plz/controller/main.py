import json
import logging
import random
import threading
import uuid
from typing import Any, Callable, Iterator, TypeVar, Union

import boto3
import docker
import requests
from flask import Flask, Response, jsonify, request, stream_with_context

from plz.controller.controller_config import config
from plz.controller.images import Images
from plz.controller.instances.aws import EC2InstanceGroup
from plz.controller.instances.instance_base import InstanceProvider
from plz.controller.instances.localhost import Localhost

T = TypeVar('T')

log = logging.getLogger('controller')
ecr_client = boto3.client('ecr')
docker_client = docker.APIClient(base_url=config.docker_host)
images = Images.from_config(config)

instance_provider: InstanceProvider
if config.run_commands_locally:
    instance_provider = Localhost.from_config(config)
else:
    instance_provider = EC2InstanceGroup.from_config(config)

_user_last_execution_id_lock = threading.RLock()
_user_last_execution_id = dict()

app = Flask(__name__)


@app.route(f'/commands', methods=['POST'])
def run_command_entrypoint():
    # Test with:
    # curl -X POST -d '{"command": "ls /" }'
    #    -H 'Content-Type: application/json' localhost:5000/commands
    command = request.json['command']
    snapshot_id = request.json['snapshot_id']
    parameters = request.json['parameters']
    execution_spec = request.json['execution_spec']
    execution_id = str(get_command_uuid())

    @_json_stream
    @stream_with_context
    def act() -> Iterator[dict]:
        yield {'id': execution_id}

        try:
            messages = instance_provider.acquire_instance(
                execution_id, execution_spec)
            for message in messages:
                yield {'status': message}
            instance = instance_provider.instance_for(execution_id)
            if instance is None:
                yield {
                    'error': 'Couldn\'t get an instance.',
                }
                return

            instance.run(
                command=command,
                snapshot_id=snapshot_id,
                parameters=parameters)
        except Exception as e:
            log.exception('Exception running command.')
            yield {'error': str(e)}

    response = Response(act(), mimetype='text/plain')
    response.status_code = requests.codes.accepted
    _set_user_last_execution_id(execution_spec['user'], execution_id)
    return response


@app.route('/commands/list', methods=['GET'])
def list_commands_entrypoint():
    # It's not protected, it's preceded by underscore as to avoid
    # name conflicts, see docs
    # noinspection PyProtectedMember
    as_dict = [info._asdict()
               for info in instance_provider.get_commands()]
    response = Response(
        json.dumps({'commands': as_dict}),
        mimetype='application/json')
    response.status_code = requests.codes.ok
    return response


@app.route('/commands/tidy', methods=['POST'])
def tidy_entry_point():
    instance_provider.tidy_up()
    response = jsonify({})
    response.status_code = requests.codes.no_content
    return response


@app.route(f'/commands/<execution_id>/status',
           methods=['GET'])
def get_status_entrypoint(execution_id):
    # Test with:
    # curl localhost:5000/commands/some-id/status
    instance = instance_provider.instance_for(execution_id)
    state = instance.get_container_state()
    if state.running:
        return jsonify({
            'running': True,
        })
    else:
        return jsonify({
            'running': False,
            'success': state.success,
            'code': state.exit_code,
        })


@app.route(f'/commands/<execution_id>/logs',
           methods=['GET'])
def get_logs_entrypoint(execution_id):
    # Test with:
    # curl localhost:5000/commands/some-id/logs
    instance = instance_provider.instance_for(execution_id)
    response = instance.logs()
    return Response(response, mimetype='application/octet-stream')


@app.route(f'/commands/<execution_id>/logs/stdout')
def get_logs_stdout_entrypoint(execution_id):
    # Test with:
    # curl localhost:5000/commands/some-id/logs/stdout
    instance = instance_provider.instance_for(execution_id)
    response = instance.logs(stdout=True, stderr=False)
    return Response(response, mimetype='application/octet-stream')


@app.route(f'/commands/<execution_id>/logs/stderr')
def get_logs_stderr_entrypoint(execution_id):
    # Test with:
    # curl localhost:5000/commands/some-id/logs/stderr
    instance = instance_provider.instance_for(execution_id)
    response = instance.logs(stdout=False, stderr=True)
    return Response(response, mimetype='application/octet-stream')


@app.route(f'/commands/<execution_id>/output/files')
def get_output_files_entrypoint(execution_id):
    # Test with:
    # curl localhost:5000/commands/some-id/output | tar x -C /tmp/plz-output
    instance = instance_provider.instance_for(execution_id)
    response = instance.output_files_tarball()
    return Response(response, mimetype='application/octet-stream')


@app.route(f'/commands/<execution_id>',
           methods=['DELETE'])
def delete_process(execution_id):
    # Test with:
    # curl -XDELETE localhost:5000/commands/some-id
    instance_provider.release_instance(execution_id)
    response = jsonify({})
    response.status_code = requests.codes.no_content
    return response


@app.route('/snapshots', methods=['POST'])
def create_snapshot():
    # Test with
    # { echo '{"user": "bruce", "project": "mobile"}'; cat some_file.tar.bz2; }
    #     | http localhost:5000/snapshots

    # Read a string with a json object until a newline is found.
    # Using the utf-8 decoder from the codecs module fails as it's decoding
    # beyond the new line (even using readline(). Probably it does a read()
    # and decodes everything it gets, as it's not possible to push back to
    # the request stream). We don't use readline on a BufferedReader as the
    # the request.stream is a LimitedStream that doesn't support it.
    b = None
    json_bytes = []
    while b != b'\n':
        b = request.stream.read(1)
        if len(b) == 0:
            raise ValueError('Expected json at the beginning of request')
        json_bytes.append(b)
    metadata_str = str(b''.join(json_bytes), 'utf-8')
    tag = Images.construct_tag(metadata_str)

    @stream_with_context
    @_handle_lazy_exceptions(formatter=_format_error)
    def act() -> Iterator[Union[bytes, str]]:
        # Pass the rest of the stream to `docker build`
        yield from images.build(request.stream, tag)
        instance_provider.push(tag)
        yield json.dumps({'id': tag})

    return Response(act(), mimetype='text/plain')


@app.route(f'/commands/<execution_id>/stop', methods=['POST'])
def stop_command_entrypoint(execution_id: str):
    instance_provider.stop_command(execution_id)
    response = jsonify({})
    response.status_code = requests.codes.no_content
    return response


@app.route(f'/users/<user>/last_execution_id')
def last_execution_id_entrypoint(user: str):
    last_execution_id = _get_user_last_execution_id(user)
    response_object = {}
    if last_execution_id is not None:
        response_object['execution_id'] = last_execution_id
    response = jsonify(response_object)
    response.status_code = requests.codes.ok
    return response


def get_command_uuid() -> str:
    # Recommended method for the node if you don't want to disclose the
    # physical address (see Python uuid docs)
    random_node = random.getrandbits(48) | 0x010000000000
    return str(uuid.uuid1(node=random_node))


def _json_stream(f: Callable[[], Iterator[Any]]):
    def wrapped() -> Iterator[str]:
        return (json.dumps(message) + '\n' for message in f())

    return wrapped


def _handle_lazy_exceptions(formatter: Callable[[str], T]):
    def wrapper(f):
        def wrapped():
            # noinspection PyBroadException
            try:
                for value in f():
                    yield value
            except Exception as e:
                yield formatter(str(e) + '\n')
                log.exception('Exception in response generator')

        return wrapped

    return wrapper


def _format_error(message: str) -> bytes:
    return json.dumps({'error': message}).encode('utf-8')


def _set_user_last_execution_id(user: str, execution_id: str):
    _user_last_execution_id_lock.acquire()
    _user_last_execution_id[user] = execution_id
    _user_last_execution_id_lock.release()


def _get_user_last_execution_id(user: str):
    last_execution_id = None
    _user_last_execution_id_lock.acquire()
    if user in _user_last_execution_id:
        last_execution_id = _user_last_execution_id[user]
    _user_last_execution_id_lock.release()
    return last_execution_id


app.run(host='0.0.0.0', port=config.port)
