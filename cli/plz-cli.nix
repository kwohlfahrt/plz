{ stdenv, python3, buildPythonPackage, buildPythonApplication, fetchPypi, requireFile,
  docker, prettytable, python-dateutil, requests, urllib3, paramiko, glob2,
  nose, flask,  timestamp ? null, sha256 ? null }:

let
  default_timestamp = builtins.replaceStrings ["\n"] [""] (builtins.readFile ../STABLE_BUILD_TIMESTAMP);
  version = "0.1.${if timestamp != null then (toString timestamp) else default_timestamp}";
  hash = sha256; # Avoid infinite recusion

in buildPythonApplication (rec {
  inherit version;
  name = "${pname}-${version}";
  pname = "plz-cli";

  propagatedBuildInputs = [ docker glob2 prettytable python-dateutil paramiko requests urllib3 ];
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
