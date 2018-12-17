{ timestamp ? null, sha256 ? null }:

let
  overlay = self: super: {
    pythonOverrides = super.lib.composeExtensions super.pythonOverrides (pyself: pysuper: {
      requests = pysuper.requests.overridePythonAttrs (pyold: rec {
        version = "2.21.0";

        src = pyold.src.override {
          inherit version;
          sha256 = "13jr0wkj9c2j8c0c8iaal9iivi0bpxghnsdn6lxcpnmc657q4ajh";
        };
      });
    });
  };

  pkgs = import <nixpkgs> { overlays = (import ~/.config/nixpkgs/overlays.nix) ++ [overlay]; };

in pkgs.python3.pkgs.callPackage ./plz-cli.nix { timestamp = timestamp; sha256 = sha256; }
