{ nixpkgs ? import <nixpkgs> {} }: nixpkgs.python3Packages.callPackage ./plz-cli.nix {}
