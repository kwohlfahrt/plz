{ stdenv, python3, buildPythonPackage, buildPythonApplication, fetchPypi,
  docker, prettytable, python-dateutil, requests, urllib3,
  nose, flask }:

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

  timestamp = builtins.replaceStrings ["\n"] [""] (builtins.readFile ../STABLE_BUILD_TIMESTAMP);

in buildPythonApplication rec {
  name = "${pname}-${version}";
  version = "0.1.${timestamp}";
  pname = "plz-cli";

  propagatedBuildInputs = [
    docker glob2 paramiko_2_4_2 prettytable_0_7_2 python-dateutil requests urllib3
  ];

  checkInputs = [ nose flask ];
  doCheck = true;
  checkPhase = ''
    nosetests
  '';

  src = ../.;
  sourceRoot = "plz/cli";
}
