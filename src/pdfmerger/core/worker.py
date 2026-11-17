"""The PDF worker: the only process that parses PDFs with MuPDF.

Started by the GUI (and the CLI) as ``PDFMerger.exe --worker``; on Windows it runs at
low integrity inside a job object (see ``sandbox_win``). It serves requests over
stdin/stdout using ``ipc`` framing and never touches the user's files for writing:
exports are returned as bytes and written by the caller.
"""
from __future__ import annotations

import os
import sys
from typing import BinaryIO

from . import ipc
from .errors import kind_of


def _protocol_streams() -> tuple[BinaryIO, BinaryIO]:
    """Take private copies of stdin/stdout for the protocol and point fd 1 at stderr,
    so stray prints from Python or C code can never corrupt the pipe."""
    in_fd = os.dup(0)
    out_fd = os.dup(1)
    try:
        os.dup2(2, 1)
    except OSError:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, 1)
    sys.stdout = sys.stderr
    return os.fdopen(in_fd, "rb", buffering=1 << 16), os.fdopen(out_fd, "wb", buffering=1 << 16)


def _selftest_op(op: str, req: dict) -> dict:
    """Diagnostics for ``--sandbox-selftest``; only enabled when started with --selftest."""
    if op == "_whoami":
        from . import sandbox_win
        return {"integrity": sandbox_win.current_integrity_level(), "pid": os.getpid()}
    if op == "_try_write":
        path = str(req["path"])
        try:
            with open(path, "x") as fh:
                fh.write("sandbox test")
            os.remove(path)
            return {"allowed": True}
        except OSError as exc:
            return {"allowed": False, "detail": f"{type(exc).__name__}: {exc}"}
    if op == "_try_spawn":
        import subprocess
        try:
            subprocess.run([str(req["exe"]), *map(str, req.get("args", []))], timeout=10,
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
            return {"allowed": True}
        except Exception as exc:
            return {"allowed": False, "detail": f"{type(exc).__name__}: {exc}"}
    if op == "_alloc":
        try:
            block = bytearray(int(req["mb"]) * 1024 * 1024)
            block[::4096] = b"\1" * len(block[::4096])   # touch every page
            return {"allowed": True}
        except MemoryError:
            return {"allowed": False, "detail": "MemoryError"}
    if op == "_crash":
        os._exit(3)
    if op == "_hang":
        import time
        while True:
            time.sleep(1)
    raise ValueError(f"unknown op {op!r}")


def serve(rfile: BinaryIO, wfile: BinaryIO, selftest: bool = False) -> int:
    import pymupdf

    from .. import __version__
    from .exporter import export_bytes
    from .pages import PageRef
    from .quality import EncryptionOptions, ExportOptions
    from .render import render_page
    from .sources import SourceRegistry

    pymupdf.TOOLS.mupdf_display_errors(False)
    pymupdf.TOOLS.mupdf_display_warnings(False)
    reg = SourceRegistry()

    while True:
        try:
            req, _ = ipc.recv(rfile)
        except (EOFError, OSError):
            break
        except ipc.ProtocolError:
            return 2
        op = req.get("op")
        reply: dict = {"id": req.get("id")}
        payload = b""
        try:
            if op == "hello":
                reply.update(version=__version__, mupdf=pymupdf.VersionFitz,
                             pymupdf=pymupdf.VersionBind)
            elif op == "open":
                src = reg.add(str(req["path"]), req.get("password") or None,
                              source_id=int(req["sid"]))
                meta = {k: str(v or "") for k, v in (src.doc.metadata or {}).items()}
                reply.update(page_count=src.page_count, metadata=meta)
            elif op == "close":
                sid = int(req["sid"])
                if sid in reg:
                    reg.remove(sid).doc.close()
            elif op == "render":
                src = reg.get(int(req["sid"]))
                w, h, stride, payload = render_page(src.doc, int(req["page"]), int(req["size"]))
                reply.update(w=w, h=h, stride=stride)
            elif op == "export":
                pages = [PageRef(int(s), int(i), int(r) % 360) for s, i, r in req["pages"]]
                opts = ExportOptions.from_dict(req.get("options") or {})
                enc = req.get("encryption")
                if enc:
                    opts.encryption = EncryptionOptions(**{k: enc[k] for k in enc
                                                           if k in EncryptionOptions.__dataclass_fields__})

                def progress(done, total, stage):
                    ipc.send(wfile, {"id": req.get("id"), "progress": [done, total, stage]})
                    return True

                payload = export_bytes(pages, reg, dict(req.get("metadata") or {}), opts, progress)
            elif selftest and isinstance(op, str) and op.startswith("_"):
                reply.update(_selftest_op(op, req))
            else:
                raise ValueError(f"unknown op {op!r}")
        except Exception as exc:
            reply = {"id": req.get("id"), "error": kind_of(exc),
                     "message": (str(exc) or type(exc).__name__)[:2000]}
            payload = b""
        try:
            ipc.send(wfile, reply, payload)
        except (OSError, ipc.ProtocolError):
            break
    reg.close_all()
    return 0


def main(argv: list[str]) -> int:
    if sys.platform == "win32":
        from .sandbox_win import quiet_error_mode
        quiet_error_mode()
    rfile, wfile = _protocol_streams()
    return serve(rfile, wfile, selftest="--selftest" in argv)
