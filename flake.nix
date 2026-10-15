{
  description = "land_value_research dev environment";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
  };

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
      python = pkgs.python313;
    in
    {
      devShells.${system}.default = pkgs.mkShell {
        buildInputs = [
          # Rust
          pkgs.rustc
          pkgs.cargo
          pkgs.clippy
          pkgs.rustfmt

          # Python (3.13 — PyO3 0.24 max)
          python

          # Build tools
          pkgs.maturin
          pkgs.uv
          pkgs.ruff

          # Node.js (browser_service)
          pkgs.nodejs_24
        ];

        env = {
          # maturin が正しい Python を使うように
          PYO3_PYTHON = "${python}/bin/python3";
          # curl_cffi 等の C 拡張が必要とするシステムライブラリ
          LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath [
            pkgs.stdenv.cc.cc.lib
            pkgs.zlib
          ];
        };

        shellHook = ''
          export PATH="$PWD/bin:$PATH"
          echo "land_value_research dev shell"
          echo "  rustc: $(rustc --version)"
          echo "  cargo: $(cargo --version)"
          echo "  python: $(python3 --version)"
          echo "  maturin: $(maturin --version)"
        '';
      };
    };
}
