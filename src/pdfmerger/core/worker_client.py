"""GUI/CLI side of the PDF worker (no PyMuPDF import).

Everything coming back from the worker is treated as untrusted: if a malicious PDF
compromised the worker, it could send anything, so sizes and types are validated here.
"""
from __future__ import annotations

import itertools
import os
import subprocess
import sys
import threading
from dataclasses import asdict
from typing import Callable, Optional, Sequence

from . import ipc
from .errors import ERROR_KINDS, WorkerCrashed, WorkerError
from .pages import PageRef
from .quality import ExportOptions

RENDER_MEMORY = 2 * 1024 ** 3        # long-lived worker: opening + thumbnails
EXPORT_MEMORY = 4 * 1024 ** 3        # one-shot worker per export (image rewriting)
TIMEOUTS = {"hello": 60, "open": 120, "close": 30, "render": 60, "export": 3600}
MAX_PAGES_REPLY = 1_000_000
MAX_THUMB_SIDE = 4096

ProgressCb = Callable[[int, int, str], None]


def worker_command(selftest: bool = False) -> list[str]:
    extra = ["--worker"] + (["--selftest"] if selftest else [])
    if getattr(sys, "frozen", False):
        return [sys.executable, *extra]
    src = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    code = (f"import sys; sys.path.insert(0, {src!r}); "
            "from pdfmerger.app import main; sys.exit(main())")
    return [sys.executable, "-c", code, *extra]


def _sandbox_disabled() -> bool:
    return os.environ.get("PDFMERGER_NO_SANDBOX", "") == "1"


def launch_worker(memory_limit: int, selftest: bool = False):
    argv = worker_command(selftest)
    if sys.platform == "win32" and not getattr(sys, "frozen", False):
        # Running from source (development, tests): the sandbox is built for the frozen
        # PDFMerger.exe. A Python interpreter does not start inside it (a venv's python.exe
        # is a launcher that needs a child process, and the base interpreter dies with
        # STATUS_DLL_INIT_FAILED), so the worker runs as a plain separate process. CI
        # checks the real sandbox with `PDFMerger.exe --sandbox-selftest`.
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, close_fds=True,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        proc.level = "unsandboxed"
        proc.mitigations = []
        return proc
    if sys.platform == "win32":
        from . import sandbox_win
        # Troubleshooting only: PDFMERGER_SANDBOX_MITIGATIONS=none|name,name,...
        env = os.environ.get("PDFMERGER_SANDBOX_MITIGATIONS")
        mitigations = None if env is None else [m for m in env.split(",") if m and m != "none"]
        return sandbox_win.launch(argv, memory_limit, mitigations=mitigations,
                                  low_integrity=not _sandbox_disabled())

    def limits():  # POSIX: cap address space; runs in the child before exec
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_AS, (memory_limit * 2, memory_limit * 2))
        except Exception:
            pass

    proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, preexec_fn=limits, close_fds=True)
    proc.level = "rlimit-only"
    proc.mitigations = []
    return proc


class WorkerClient:
    """Thread-safe, auto-restarting connection to one worker process."""

    def __init__(self, memory_limit: int = RENDER_MEMORY, selftest: bool = False):
        self._memory = memory_limit
        self._selftest = selftest
        self._lock = threading.RLock()
        self._proc = None
        self._ids = itertools.count(1)
        self._sources: dict[int, tuple[str, Optional[str]]] = {}
        self.restarts = 0
        self.info: dict = {}

    # ---- process management ---------------------------------------------
    @property
    def sandbox_level(self) -> str:
        with self._lock:
            self._ensure()
            return getattr(self._proc, "level", "unknown")

    def _ensure(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return
        if self._proc is not None:     # died between calls
            self._discard()
            self.restarts += 1
        self._proc = launch_worker(self._memory, self._selftest)
        self.info = self._call_raw("hello")[0]
        for sid, (path, password) in list(self._sources.items()):   # replay after a crash
            try:
                self._call_raw("open", sid=sid, path=path, password=password)
            except WorkerCrashed:
                raise
            except Exception:
                self._sources.pop(sid, None)

    def _discard(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            proc.kill()
        except Exception:
            pass
        if hasattr(proc, "close"):
            proc.close()
        else:
            for f in (proc.stdin, proc.stdout):
                try:
                    f.close()
                except Exception:
                    pass
            try:
                proc.wait(5)
            except Exception:
                pass

    def kill(self) -> None:
        """Kill the worker now (used to cancel an export); safe from any thread."""
        proc = self._proc
        if proc is not None:
            try:
                proc.kill()
            except Exception:
                pass

    def shutdown(self) -> None:
        with self._lock:
            self._discard()

    # ---- requests --------------------------------------------------------------
    def _call_raw(self, op: str, payload: bytes = b"", progress: Optional[ProgressCb] = None,
                  **fields) -> tuple[dict, bytes]:
        proc = self._proc
        rid = next(self._ids)
        timer = threading.Timer(TIMEOUTS.get(op, 120), self.kill)
        timer.daemon = True
        timer.start()
        try:
            ipc.send(proc.stdin, {"id": rid, "op": op, **fields}, payload)
            while True:
                header, data = ipc.recv(proc.stdout)
                if header.get("id") != rid:
                    raise ipc.ProtocolError("unexpected reply id")
                prog = header.get("progress")
                if prog is None:
                    break
                if (progress and isinstance(prog, list) and len(prog) == 3
                        and all(isinstance(x, int) for x in prog[:2])):
                    progress(prog[0], prog[1], str(prog[2])[:32])
        except (EOFError, OSError, ValueError, ipc.ProtocolError) as exc:
            code = None
            try:
                proc.wait(2) if hasattr(proc, "wait") else None
                code = proc.poll()
            except Exception:
                pass
            self._discard()
            self.restarts += 1
            detail = f"{exc}" + (f", exit code {code:#x}" if isinstance(code, int) else "")
            raise WorkerCrashed(f"the PDF worker stopped during '{op}' ({detail})") from None
        finally:
            timer.cancel()
        if "error" in header:
            cls = ERROR_KINDS.get(header.get("error"), WorkerError)
            raise cls(str(header.get("message", ""))[:2000])
        return header, data

    def call(self, op: str, payload: bytes = b"", progress: Optional[ProgressCb] = None,
             **fields) -> tuple[dict, bytes]:
        with self._lock:
            self._ensure()
            return self._call_raw(op, payload, progress, **fields)

    # ---- typed API -----------------------------------------------------------
    def hello(self) -> dict:
        with self._lock:
            self._ensure()
            return dict(self.info)

    @staticmethod
    def _validate_open(header: dict) -> tuple[int, dict]:
        count = header.get("page_count")
        if type(count) is not int or not 0 < count <= MAX_PAGES_REPLY:
            raise WorkerError("invalid page count from worker")
        meta = header.get("metadata")
        meta = {str(k)[:64]: str(v)[:4096] for k, v in meta.items()} if isinstance(meta, dict) else {}
        return count, meta

    @staticmethod
    def _validate_render(header: dict, data: bytes) -> tuple[int, int, int, bytes]:
        w, h, stride = header.get("w"), header.get("h"), header.get("stride")
        if not all(type(v) is int for v in (w, h, stride)):
            raise WorkerCrashed("invalid render reply")
        if not (0 < w <= MAX_THUMB_SIDE and 0 < h <= MAX_THUMB_SIDE and stride >= 3 * w
                and len(data) == stride * h):
            raise WorkerCrashed("invalid render reply")
        return w, h, stride, data

    @staticmethod
    def _validate_export(data: bytes) -> bytes:
        if not data.startswith(b"%PDF-"):
            raise WorkerCrashed("the worker did not return a PDF")
        return data

    def open(self, sid: int, path: str, password: Optional[str]) -> tuple[int, dict]:
        header, _ = self.call("open", sid=sid, path=path, password=password)
        count, meta = self._validate_open(header)
        with self._lock:
            self._sources[sid] = (path, password)
        return count, meta

    def close_source(self, sid: int) -> None:
        with self._lock:
            self._sources.pop(sid, None)
            if self._proc is not None and self._proc.poll() is None:
                try:
                    self._call_raw("close", sid=sid)
                except Exception:
                    pass

    def render(self, sid: int, page: int, size: int) -> tuple[int, int, int, bytes]:
        header, data = self.call("render", sid=sid, page=page, size=size)
        return self._validate_render(header, data)

    def export(self, pages: Sequence[PageRef], metadata: dict, opts: ExportOptions,
               progress: Optional[ProgressCb] = None) -> bytes:
        enc = asdict(opts.encryption) if opts.encryption else None
        _, data = self.call("export", progress=progress,
                            pages=[[p.source_id, p.page_index, p.rotation] for p in pages],
                            metadata={k: v for k, v in metadata.items() if v},
                            options=opts.to_dict(), encryption=enc)
        return self._validate_export(data)
