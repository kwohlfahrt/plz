{ stdenv, python3, buildPythonPackage, buildPythonApplication, fetchPypi, requireFile,
  docker, prettytable, python-dateutil, requests, urllib3,
  nose, flask,  timestamp ? null, sha256 ? null }:

let
  glob2 = buildPythonPackage rec {
    version = "0.6";
    pname = "glob2";

    src = fetchPypi {
      inherit pname version;
      sha256 = "1miyz0pjyji4gqrzl04xsxcylk3h2v9fvi7hsg221y11zy3adc7m";
    };
  };

  prettytable_0_7_2 = prettytable.overridePythonAttrs rec {
    pname = "prettytable";
    version = "0.7.2";

    src = fetchPypi {
      inherit pname version;
      sha256 = "1ndckiniasacfqcdafzs04plskrcigk7vxprr2y34jmpkpf60m1d";
    };
  };

  paramiko_2_4_2 = python3.pkgs.callPackage ./paramiko.nix {};

  default_timestamp = builtins.replaceStrings ["\n"] [""] (builtins.readFile ../STABLE_BUILD_TIMESTAMP);
  version = "0.1.${if timestamp != null then (toString timestamp) else default_timestamp}";
  hash = sha256; # Avoid infinite recusion

in buildPythonApplication (rec {
  inherit version;
  name = "${pname}-${version}";
  pname = "plz-cli";

  propagatedBuildInputs = [
    docker glob2 paramiko_2_4_2 prettytable_0_7_2 python-dateutil requests urllib3
  ];
} // (if timestamp == null then {
  src = ../.;
  sourceRoot = "plz/cli";

  checkInputs = [ nose flask ];
  doCheck = true;
  checkPhase = ''
    nosetests
  '';
} else {
  format = "wheel";

  src = requireFile rec {
    name = "plz_cli-${version}-py3-none-any.whl";
    sha256 = if hash != null then hash else abort message;

    message = ''
      When installing a specific timestamp, ${name} must be prefetched. Run:

          nix-prefetch-url "https://s3-eu-west-1.amazonaws.com/plz.prodo.ai/${name}"

      and then re-run the derivation with the `sha256` argument.
    '';
  };
}))
