{ stdenv, buildPythonPackage, fetchPypi, cryptography, pyasn1, bcrypt, pynacl, pytest, nose, mock,
  # pytest-relaxed
  decorator, six
}:

let
  pytest_32 = pytest.overridePythonAttrs rec {
    pname = "pytest";
    version = "3.2.5";

    src = fetchPypi {
      inherit pname version;
      sha256 = "10cbsyyyzamhvi1gqqyhccsx906xlcwcgddvldalqi1v27vx8nvd";
    };
  };

  pytest-relaxed = buildPythonPackage rec {
    pname = "pytest-relaxed";
    version = "1.1.4";

    src = fetchPypi {
      inherit pname version;
      sha256 = "0ip10kp1dn9fkpvp3vqcvz71m3rfdr8n8y0z8pangaib4mrw86ji";
    };

    propagatedBuildInputs = [ decorator six pytest_32 ];

    checkPhase = ''
      pytest
    '';
  };

in buildPythonPackage rec {
  pname = "paramiko";
  version = "2.4.2";

  src = fetchPypi {
    inherit pname version;
    sha256 = "1jqgj2gl1pz7bi2aab1r2xq0ml0gskmm9p235cg9y32nydymm5x8";
  };

  propagatedBuildInputs = [ cryptography pyasn1 bcrypt pynacl ];

  checkInputs = [ pytest-relaxed pytest_32 nose mock ];
  checkPhase = ''
    pytest --ignore tests/test_sftp.py
  '';

  meta = with stdenv.lib; {
    homepage = "https://github.com/paramiko/paramiko/";
    description = "Native Python SSHv2 protocol library";
    license = licenses.lgpl21Plus;
    maintainers = with maintainers; [ aszlig ];

    longDescription = ''
      This is a library for making SSH2 connections (client or server).
      Emphasis is on using SSH2 as an alternative to SSL for making secure
      connections between python scripts. All major ciphers and hash methods
      are supported. SFTP client and server mode are both supported too.
    '';
  };
}
