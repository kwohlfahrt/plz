{ timestamp ? null, sha256 ? null }:

let
  overlay = self: super: {
    python3 = super.python3.override {
      packageOverrides = pyself: pysuper: {
        requests = pysuper.requests.overridePythonAttrs (pyold: rec {
          version = "2.21.0";

          src = pyold.src.override {
            inherit version;
            sha256 = "13jr0wkj9c2j8c0c8iaal9iivi0bpxghnsdn6lxcpnmc657q4ajh";
          };
        });

        glob2 = pyself.buildPythonPackage rec {
          version = "0.6";
          pname = "glob2";

          src = pyself.fetchPypi {
            inherit pname version;
            sha256 = "1miyz0pjyji4gqrzl04xsxcylk3h2v9fvi7hsg221y11zy3adc7m";
          };
        };
      };
    };
  };

  pkgs = import <nixpkgs> { overlays = [overlay]; };

in pkgs.python3.pkgs.callPackage ./plz-cli.nix { timestamp = timestamp; sha256 = sha256; }
