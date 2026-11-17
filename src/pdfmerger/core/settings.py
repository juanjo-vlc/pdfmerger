"""Portable settings: settings.ini next to the executable when writable,
otherwise in the per-user config directory. Never touches the registry."""
from __future__ import annotations

import os
import sys
import tempfile
from typing import Optional

from PySide6.QtCore import QSettings

ORG = "PDFMerger"
INI_NAME = "settings.ini"


def app_dir() -> str:
    """Directory of the running executable (frozen) or the project root (dev)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def user_config_dir() -> str:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~\\AppData\\Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, ORG)


def _is_writable_dir(path: str) -> bool:
    if not os.path.isdir(path):
        return False
    try:
        # mkstemp uses O_CREAT|O_EXCL with a random name: never follows or truncates links
        fd, probe = tempfile.mkstemp(prefix=".write_test_", dir=path)
    except OSError:
        return False
    os.close(fd)
    try:
        os.remove(probe)
    except OSError:
        pass
    return True


def settings_path(portable_dir: Optional[str] = None, fallback_dir: Optional[str] = None) -> str:
    portable_dir = portable_dir or app_dir()
    portable_ini = os.path.join(portable_dir, INI_NAME)
    if os.path.isfile(portable_ini) and os.access(portable_ini, os.W_OK):
        return portable_ini
    if not os.path.exists(portable_ini) and _is_writable_dir(portable_dir):
        return portable_ini
    fallback_dir = fallback_dir or user_config_dir()
    os.makedirs(fallback_dir, exist_ok=True)
    return os.path.join(fallback_dir, INI_NAME)


_settings: Optional[QSettings] = None


def settings() -> QSettings:
    global _settings
    if _settings is None:
        _settings = QSettings(settings_path(), QSettings.Format.IniFormat)
    return _settings


def set_settings(s: QSettings) -> None:
    """Override the global settings object (tests)."""
    global _settings
    _settings = s
