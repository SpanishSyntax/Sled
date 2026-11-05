{
  description = "Sled - Central Model Context Protocol (MCP) Store & Server Bridge for the SpanishSyntax Ecosystem";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    prism = {
      url = "github:SpanishSyntax/Prism";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = {
    self,
    nixpkgs,
    flake-utils,
    prism,
  }: let
    systems = flake-utils.lib.defaultSystems;
  in
    flake-utils.lib.eachSystem systems (system: let
      pkgs = import nixpkgs {
        inherit system;
        overlays = [prism.overlays.default];
      };
      lib = pkgs.lib;
      pythonPackages = pkgs.python3Packages;
      python = pythonPackages.python;

      runtimeBins = with pkgs; [
        git
        nix
        direnv
        iproute2
        procps
        coreutils
        iputils
        ripgrep
        fd
        jq
        util-linux
        dnsutils
        glib
        libnotify
      ];

      sledPackage = pythonPackages.buildPythonApplication {
        pname = "sled";
        version = "0.1.0";
        src = lib.cleanSource ./.;
        pyproject = true;

        build-system = [
          pythonPackages.setuptools
        ];

        dependencies = [
          pythonPackages.mcp
          pythonPackages.prism
          pythonPackages.httpx
        ];

        nativeBuildInputs = [
          pkgs.makeWrapper
        ];

        postFixup = ''
          wrapProgram $out/bin/sled \
            --prefix PATH : ${lib.makeBinPath runtimeBins}
        '';

        pythonImportsCheck = [
          "sled"
          "sled.main"
          "sled.ui"
          "sled.tools"
          "sled.tools.fs"
          "sled.tools.git"
          "sled.tools.system"
          "sled.tools.docker"
          "sled.tools.systemd"
          "sled.tools.nixos"
          "sled.tools.network"
          "sled.tools.dev"
        ];

        doCheck = false;

        meta = with lib; {
          description = "Central Model Context Protocol (MCP) store & server bridge for the SpanishSyntax & Frost ecosystem";
          homepage = "https://github.com/SpanishSyntax/Sled";
          license = licenses.mit;
          mainProgram = "sled";
          platforms = platforms.unix;
        };
      };

      devPythonEnv = python.withPackages (ps: [
        ps.mcp
        ps.prism
        ps.httpx
        ps.setuptools
        ps.pytest
        ps.ruff
      ]);
    in {
      packages = {
        default = sledPackage;
        sled = sledPackage;
      };

      apps = {
        default = {
          type = "app";
          program = "${sledPackage}/bin/sled";
        };
        sled = {
          type = "app";
          program = "${sledPackage}/bin/sled";
        };
      };

      devShells.default = pkgs.mkShell {
        packages = [
          devPythonEnv
          pkgs.uv
          pkgs.nil
          pkgs.nixd
          pkgs.nixfmt-rfc-style
          pkgs.git
          pkgs.direnv
        ];

        env = {
          UV_PYTHON = "${devPythonEnv}/bin/python3";
          UV_PYTHON_DOWNLOADS = "never";
        };

        shellHook = ''
          printf '\033[1;36m🛷 [sled]\033[0m ⚡ \033[1mDevShell\033[0m (Python %s, uv %s, nil + nixd LSP) active\n' \
            "$(python3 --version | cut -d' ' -f2)" \
            "$(uv --version | cut -d' ' -f2)" >&2
        '';
      };
    })
    // {
      overlays = {
        default = final: prev: {
          sled = self.packages.${prev.stdenv.hostPlatform.system}.default;
        };
        sled = self.overlays.default;
      };

      nixosModules = {
        default = self.nixosModules.sled;
        sled = {
          config,
          lib,
          pkgs,
          ...
        }: let
          cfg = config.programs.sled;
          system = pkgs.stdenv.hostPlatform.system;
        in {
          options.programs.sled = {
            enable = lib.mkEnableOption "Sled - Central Model Context Protocol (MCP) store & server bridge";
            package = lib.mkOption {
              type = lib.types.package;
              default = self.packages.${system}.default;
              description = "The Sled package to install system-wide.";
            };
          };

          config = lib.mkIf cfg.enable {
            environment.systemPackages = [cfg.package];
          };
        };
      };

      homeManagerModules = {
        default = self.homeManagerModules.sled;
        sled = {
          config,
          lib,
          pkgs,
          ...
        }: let
          cfg = config.programs.sled;
          tomlFormat = pkgs.formats.toml {};
          system = pkgs.stdenv.hostPlatform.system;
          defaultSled = self.packages.${system}.default;
          mergedSettings =
            lib.recursiveUpdate
            (lib.optionalAttrs (cfg.packs != null || cfg.tools != null) {
              packs = lib.optionalAttrs (cfg.packs != null) { enabled = cfg.packs; };
              tools = lib.optionalAttrs (cfg.tools != null) { enabled = cfg.tools; };
            })
            cfg.settings;
        in {
          options.programs.sled = {
            enable = lib.mkEnableOption "Sled - Central Model Context Protocol (MCP) store & server bridge";

            package = lib.mkOption {
              type = lib.types.package;
              default = defaultSled;
              description = "The Sled package to use.";
            };

            packs = lib.mkOption {
              type = lib.types.nullOr (lib.types.listOf lib.types.str);
              default = null;
              example = ["fs" "git" "system" "docker" "systemd" "nixos" "network"];
              description = "List of Sled MCP capability packs to enable declaratively.";
            };

            tools = lib.mkOption {
              type = lib.types.nullOr (lib.types.listOf lib.types.str);
              default = null;
              example = ["ls" "cat" "grep" "git_status" "docker_ps" "journalctl"];
              description = "List of atomic MCP tools to enable declaratively.";
            };

            settings = lib.mkOption {
              type = tomlFormat.type;
              default = {};
              description = "Configuration written to ~/.config/sled/sled.toml when declarative mode is used.";
            };
          };

          config = lib.mkIf cfg.enable {
            home.packages = [cfg.package];
            xdg.configFile."sled/sled.toml" = lib.mkIf (mergedSettings != {}) {
              source = tomlFormat.generate "sled.toml" mergedSettings;
            };
          };
        };
      };
    };
}
