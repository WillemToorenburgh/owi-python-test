with import <nixpkgs> {};
  pkgs.mkShell rec {
    name = "python-build-venv";
    venvDir = "./.venv";
    buildInputs = [
      python3
      python312Packages.venvShellHook
    ];
    postVenvCreation = ''
      unset SOURCE_DATE_EPOCH
      pip install -r requirements.txt
    '';
  }
