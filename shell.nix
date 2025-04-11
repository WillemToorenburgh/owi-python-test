with import <nixpkgs> {}; let
  pythonEnv = python3.withPackages (ps:
    with ps; [
      google-api-python-client
      google-auth-httplib2
      google-auth-oauthlib
      pytest
      pylance
      debugpy
      pylint
      pyinstaller
      cython
    ]);
in
  pythonEnv.env
