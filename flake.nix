{
  inputs = {
    nixpkgs.url = "nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    flake-compat.url = "github:edolstra/flake-compat";
  };
  outputs = { nixpkgs, flake-utils, ... }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        lib = pkgs.lib;
      in
      {
        packages = rec {
          glasgow = pkgs.glasgow.overrideAttrs {
            version = "";
            src = ./.;
          };
          default = glasgow;
        };

        devShell = pkgs.mkShell {
          packages = with pkgs; [
            yosys
            icestorm
            nextpnr

            sdcc

            (python3.withPackages (pypkgs: with pypkgs; [
              typing-extensions
              amaranth
              packaging
              platformdirs
              fx2
              libusb1
              pyvcd
              aiohttp

              unittestCheckHook
            ]))
          ];

          YOSYS="${lib.getBin pkgs.yosys}/bin/yosys";
          ICEPACK="${lib.getBin pkgs.icestorm}/bin/icepack";
          NEXTPNR_ICE40="${lib.getBin pkgs.nextpnr}/bin/nextpnr-ice40";
        };

        formatter = pkgs.nixfmt-rfc-style;
      }
    );
}
