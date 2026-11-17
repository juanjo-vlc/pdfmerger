"""``PDFMerger.exe --sandbox-selftest [sample.pdf] [--log FILE]``

Starts a worker exactly as the application does and checks that the sandbox holds:
it must not be able to write to the user's folders, start programs or exceed its
memory limit, and crashes/hangs must be contained. Exit code 0 = all checks passed.
"""
from __future__ import annotations

import os
import sys
import tempfile
from typing import Callable

from .errors import WorkerCrashed
from . import worker_client
from .worker_client import RENDER_MEMORY, WorkerClient


def main(argv: list[str]) -> int:
    log_path = next((argv[i + 1] for i, a in enumerate(argv[:-1]) if a == "--log"), None)
    pdfs = [a for a in argv[1:] if a.lower().endswith(".pdf")]
    lines: list[str] = []
    failures = 0
    windows = sys.platform == "win32"

    def out(msg: str) -> None:
        lines.append(msg)
        if sys.stderr:
            try:
                print(msg, file=sys.stderr)
            except Exception:
                pass

    def check(name: str, fn: Callable[[], tuple[bool, str]]) -> None:
        nonlocal failures
        try:
            ok, detail = fn()
        except Exception as exc:
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        failures += 0 if ok else 1
        out(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")

    worker_client.TIMEOUTS["_hang"] = 5
    client = WorkerClient(memory_limit=RENDER_MEMORY, selftest=True)
    try:
        info = client.hello()
        level = client.sandbox_level
        out(f"worker: PDF Merger {info.get('version')} / MuPDF {info.get('mupdf')}; "
            f"sandbox={level}; mitigations={','.join(getattr(client._proc, 'mitigations', []))}")

        if windows:
            check("runs at low integrity",
                  lambda: ((r := client.call("_whoami")[0])["integrity"] == "low",
                           f"integrity={r['integrity']}"))
            targets = [os.path.expanduser("~"), tempfile.gettempdir(),
                       os.path.join(os.path.expanduser("~"), "Documents")]
            for folder in targets:
                if not os.path.isdir(folder):
                    continue
                probe = os.path.join(folder, f"pdfmerger-sandbox-probe-{os.getpid()}.txt")

                def write_blocked(probe=probe):
                    r = client.call("_try_write", path=probe)[0]
                    leaked = os.path.exists(probe)
                    if leaked:
                        os.remove(probe)
                    return (not r["allowed"] and not leaked,
                            "blocked" if not r["allowed"] else "WRITE ALLOWED")
                check(f"cannot write to {folder}", write_blocked)
            comspec = os.environ.get("ComSpec", r"C:\Windows\System32\cmd.exe")
            check("cannot start programs",
                  lambda: ((r := client.call("_try_spawn", exe=comspec, args=["/c", "exit"])[0])
                           ["allowed"] is False, r.get("detail", "SPAWN ALLOWED")))
        else:
            out("SKIP  file-system and process restrictions: only enforced on Windows")

        def memory_capped():
            mb = int(RENDER_MEMORY * 2.5) // (1024 * 1024)
            try:
                r = client.call("_alloc", mb=mb)[0]
                return (not r["allowed"], f"{mb} MB allocation {'refused' if not r['allowed'] else 'ALLOWED'}")
            except WorkerCrashed:
                return True, f"{mb} MB allocation killed the worker (contained)"
        check("memory limit enforced", memory_capped)

        def crash_contained():
            before = client.restarts
            try:
                client.call("_crash")
                return False, "worker did not crash"
            except WorkerCrashed:
                pass
            client.hello()
            return client.restarts == before + 1, "worker crashed and was restarted"
        check("crash is contained", crash_contained)

        def hang_contained():
            try:
                client.call("_hang")
                return False, "returned"
            except WorkerCrashed:
                client.hello()
                return True, "hung worker was killed after the timeout and restarted"
        check("hang is contained", hang_contained)

        for i, pdf in enumerate(pdfs, start=1):
            def opens(pdf=pdf, sid=i):
                count, _ = client.open(sid, os.path.abspath(pdf), None)
                w, h, _, data = client.render(sid, 0, 128)
                return True, f"{count} pages, first page rendered {w}x{h}"
            check(f"opens and renders {os.path.basename(pdf)}", opens)
    except Exception as exc:
        failures += 1
        out(f"FAIL  worker could not be started: {type(exc).__name__}: {exc}")
    finally:
        client.shutdown()

    out("RESULT: " + ("all checks passed" if not failures else f"{failures} check(s) failed"))
    if log_path:
        with open(log_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    return 0 if not failures else 1
