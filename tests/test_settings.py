import os
import stat
import sys

import pytest

from pdfmerger.core.settings import settings_path


def test_portable_when_writable(tmp_path):
    p = settings_path(str(tmp_path), str(tmp_path / "fb"))
    assert p == str(tmp_path / "settings.ini")


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="POSIX permissions")
def test_fallback_when_readonly(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    app.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        p = settings_path(str(app), str(tmp_path / "fb"))
        assert p == str(tmp_path / "fb" / "settings.ini")
    finally:
        app.chmod(stat.S_IRWXU)


def test_existing_portable_ini_wins(tmp_path):
    (tmp_path / "settings.ini").write_text("")
    assert settings_path(str(tmp_path), str(tmp_path / "fb")) == str(tmp_path / "settings.ini")
