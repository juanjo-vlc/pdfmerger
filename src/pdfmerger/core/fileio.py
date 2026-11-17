"""File helpers (no PyMuPDF import)."""
from __future__ import annotations

import os
import tempfile


def same_file(a: str, b: str) -> bool:
    """True if both paths name the same file (follows links, case-insensitive on Windows)."""
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def write_atomic(path: str, data: bytes) -> int:
    """Write ``data`` to a temp file next to ``path`` and rename it into place."""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(suffix=".pdf.tmp", dir=directory)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return os.path.getsize(path)
