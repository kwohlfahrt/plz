{ nixpkgs ? import <nixpkgs> {}, timestamp ? null, sha256 ? null }:

nixpkgs.python3Packages.callPackage ./plz-cli.nix { timestamp = timestamp; sha256 = sha256;}
