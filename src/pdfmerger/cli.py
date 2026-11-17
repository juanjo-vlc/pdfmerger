"""Command-line (headless) export:

    PDFMerger.exe --export OUT.pdf [--preset original|print|ebook|screen]
                  [--title T] [--author A] [--subject S] [--keywords K]
                  [--sanitize] [--password-file FILE] [--input-password-file FILE]
                  [--log LOG.txt] IN1.pdf [IN2.pdf ...]

Passwords are read from files (first line), or from standard input when FILE is "-",
never from the command line, which other processes and shell history can see.

Pages of all inputs are concatenated in order. The exit code is 0 on success.
The Windows build is a GUI program without a console, so ``--log`` can be used to
capture messages in a file.
"""
from __future__ import annotations

import argparse
import sys
from typing import Optional

from . import APP_NAME, __version__
import os

from .core.errors import PasswordRequired
from .core.fileio import same_file, write_atomic
from .core.pages import PageRef
from .core.quality import PRESETS, EncryptionOptions, ExportOptions, apply_preset
from .core.worker_client import EXPORT_MEMORY, WorkerClient


def _read_lines(path: str) -> list[str]:
    if path == "-":
        data = sys.stdin.read() if sys.stdin else ""
    else:
        with open(path, encoding="utf-8-sig") as fh:
            data = fh.read()
    return [line.rstrip("\r\n") for line in data.splitlines() if line.strip()]


def wants_cli(argv: list[str]) -> bool:
    return any(a in ("--export", "--help-cli", "--version", "--sandbox-selftest")
               for a in argv[1:])


def run(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="PDFMerger", description="Merge PDF files without the GUI.",
                                allow_abbrev=False)
    p.add_argument("--export", metavar="OUT", help="output PDF file")
    p.add_argument("--preset", choices=list(PRESETS), default="original")
    p.add_argument("--jpeg-quality", type=int, help="override the preset's JPEG quality")
    p.add_argument("--title")
    p.add_argument("--author")
    p.add_argument("--subject")
    p.add_argument("--keywords")
    p.add_argument("--sanitize", action="store_true",
                   help="remove links, form fields, JavaScript, attachments and XMP metadata")
    p.add_argument("--password-file", metavar="FILE",
                   help='encrypt the output (AES-256) with the password in FILE ("-" = stdin)')
    p.add_argument("--input-password-file", metavar="FILE",
                   help='passwords for encrypted inputs, one per line ("-" = stdin)')
    p.add_argument("--log", help="write messages to this file")
    p.add_argument("--version", action="store_true")
    p.add_argument("--help-cli", action="help")
    p.add_argument("inputs", nargs="*")
    if "--sandbox-selftest" in argv[1:]:
        from .core.selftest import main as selftest_main
        return selftest_main(argv)
    # Open the log before parsing so argument errors are captured too: the Windows
    # build has no console, so argparse's stderr output would otherwise be lost.
    log_path = next((argv[i + 1] for i, a in enumerate(argv[:-1]) if a == "--log"), None)
    log = open(log_path, "w", encoding="utf-8") if log_path else None
    try:
        p.exit_on_error = False
        args = p.parse_args(argv[1:])
    except (argparse.ArgumentError, SystemExit) as exc:
        if isinstance(exc, SystemExit) and exc.code in (0, None):
            raise
        if log:
            log.write(f"error: {exc}\n{p.format_usage()}")
            log.close()
        return 2

    def say(msg: str) -> None:
        if log:
            log.write(msg + "\n")
            log.flush()
        if sys.stderr:
            try:
                print(msg, file=sys.stderr)
            except Exception:
                pass

    try:
        if args.version:
            say(f"{APP_NAME} {__version__}")
            return 0
        if not args.export or not args.inputs:
            say("error: --export OUT.pdf and at least one input file are required")
            return 2
        if args.password_file == "-" and args.input_password_file == "-":
            say("error: only one of the password options can read from stdin")
            return 2
        out_password = (_read_lines(args.password_file) or [""])[0] if args.password_file else ""
        input_passwords = _read_lines(args.input_password_file) if args.input_password_file else []
        if os.path.exists(args.export) and any(same_file(args.export, p) for p in args.inputs):
            say("error: ValueError: The output file is one of the input files")
            return 1
        # All PDF parsing happens in the sandboxed worker process.
        client = WorkerClient(memory_limit=EXPORT_MEMORY)
        pages: list[PageRef] = []
        for sid, path in enumerate(args.inputs, start=1):
            count = None
            last: Exception = PasswordRequired(path)
            for pw in [None] + input_passwords:
                try:
                    count, _ = client.open(sid, os.path.abspath(path), pw)
                    break
                except PasswordRequired as exc:
                    last = exc
                except Exception as exc:
                    last = exc
                    break
            if count is None:
                client.shutdown()
                say(f"error: cannot open {path}: {type(last).__name__} {last}")
                return 1
            pages += [PageRef(sid, i) for i in range(count)]
        opts = apply_preset(ExportOptions(), args.preset)
        if args.jpeg_quality:
            opts.recompress = True
            opts.jpeg_quality = args.jpeg_quality
        opts.sanitize = args.sanitize
        if args.password_file:
            if not out_password:
                say("error: the password file is empty")
                return 2
            opts.encryption = EncryptionOptions(user_password=out_password)
        meta = {"title": args.title, "author": args.author, "subject": args.subject,
                "keywords": args.keywords, "producer": f"{APP_NAME} {__version__}"}
        try:
            data = client.export(pages, meta, opts)
        finally:
            client.shutdown()
        size = write_atomic(args.export, data)
        say(f"ok: wrote {args.export} ({len(pages)} pages, {size} bytes)")
        return 0
    except Exception as exc:
        say(f"error: {type(exc).__name__}: {exc}")
        return 1
    finally:
        if log:
            log.close()
