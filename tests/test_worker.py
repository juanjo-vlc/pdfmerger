"""The sandboxed worker process and the client's handling of untrusted replies."""
import io
import os
import subprocess
import sys
import textwrap

import pymupdf
import pytest

from pdfmerger.core import ipc, worker_client
from pdfmerger.core.errors import (NotAPdf, PasswordRequired, UnsafePdf, WorkerCrashed,
                                   WorkerError)
from pdfmerger.core.pages import PageRef
from pdfmerger.core.quality import EncryptionOptions, ExportOptions
from pdfmerger.core.worker_client import WorkerClient

from conftest import page_labels


@pytest.fixture
def client():
    c = WorkerClient(selftest=True)
    yield c
    c.shutdown()


def test_open_render_export(client, pdf_a, pdf_b):
    assert client.open(1, pdf_a, None)[0] == 3
    assert client.open(2, pdf_b, None)[0] == 2
    w, h, stride, data = client.render(1, 0, 128)
    assert max(w, h) == 128 and len(data) == stride * h
    stages = []
    pdf = client.export([PageRef(2, 1), PageRef(1, 0, 90)], {"title": "W"}, ExportOptions(),
                        progress=lambda d, t, s: stages.append(s))
    assert "saving" in stages
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    assert [p.get_text().strip() for p in doc] == ["B2", "A1"]
    assert doc[1].rotation == 90 and doc.metadata["title"] == "W"


def test_errors_are_mapped(client, pdf_locked, tmp_path, monkeypatch):
    with pytest.raises(PasswordRequired):
        client.open(1, pdf_locked, None)
    assert client.open(1, pdf_locked, "secret")[0] == 1
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf")
    with pytest.raises(NotAPdf):
        client.open(2, str(bad), None)


def test_encrypted_export_through_worker(client, pdf_a):
    client.open(1, pdf_a, None)
    opts = ExportOptions(encryption=EncryptionOptions(user_password="pw"))
    doc = pymupdf.open(stream=client.export([PageRef(1, 0)], {}, opts), filetype="pdf")
    assert doc.needs_pass and doc.authenticate("pw") and not doc.authenticate("pw") & 4


def test_crash_restarts_and_reopens_sources(client, pdf_a):
    client.open(1, pdf_a, None)
    first_pid = client._proc.pid
    with pytest.raises(WorkerCrashed):
        client.call("_crash")
    # the next request starts a new worker and transparently re-opens the documents
    w, h, _, _ = client.render(1, 2, 64)
    assert client._proc.pid != first_pid and client.restarts == 1 and max(w, h) == 64


def test_hang_is_killed(client, monkeypatch):
    monkeypatch.setitem(worker_client.TIMEOUTS, "_hang", 2)
    with pytest.raises(WorkerCrashed):
        client.call("_hang")
    assert client.hello()["version"]


def test_selftest_ops_disabled_in_normal_workers(pdf_a):
    c = WorkerClient()
    try:
        with pytest.raises(ValueError):      # "unknown op"
            c.call("_crash")
        assert c.restarts == 0      # the op was refused, the worker is still alive
    finally:
        c.shutdown()


# ---- a compromised worker must not be able to harm the GUI --------------------------
class FakeProc:
    """Pretends to be a worker that sends the given reply to the next request."""

    def __init__(self, header, payload=b""):
        self.stdin = io.BytesIO()
        out = io.BytesIO()
        ipc.send(out, {"id": 1, **header}, payload)
        out.seek(0)
        self.stdout = out
        self.level = "fake"

    def poll(self):
        return None

    def kill(self):
        pass

    def wait(self, timeout=None):
        return 0


@pytest.mark.parametrize("header,payload", [
    ({"w": 100000, "h": 1, "stride": 300000}, b"x" * 300000),   # absurd dimensions
    ({"w": 10, "h": 10, "stride": 30}, b"short"),                # size mismatch
    ({"w": "10", "h": 10, "stride": 30}, b"x" * 300),            # wrong types
    ({"w": 10, "h": 10, "stride": 10}, b"x" * 100),              # stride too small
])
def test_rejects_malformed_render_replies(header, payload):
    c = WorkerClient()
    c._proc = FakeProc(header, payload)
    with pytest.raises(WorkerCrashed):
        hdr, data = c._call_raw("render", sid=1, page=0, size=10)   # bypasses _ensure()
        c._validate_render(hdr, data)


@pytest.mark.parametrize("header", [{"page_count": -1}, {"page_count": "9"},
                                    {"page_count": 10 ** 9}, {}])
def test_rejects_malformed_open_replies(header):
    c = WorkerClient()
    c._proc = FakeProc({"metadata": {}, **header})
    with pytest.raises(WorkerError):
        hdr, _ = c._call_raw("open", sid=1, path="x", password=None)
        c._validate_open(hdr)


def test_rejects_non_pdf_export_reply():
    c = WorkerClient()
    c._proc = FakeProc({}, b"MZ\x90\x00 definitely not a pdf")
    with pytest.raises(WorkerCrashed):
        _, data = c._call_raw("export")
        c._validate_export(data)


def test_rejects_oversized_frames():
    buf = io.BytesIO(ipc.HEADER.pack(ipc.MAX_JSON + 1, 0))
    with pytest.raises(ipc.ProtocolError):
        ipc.recv(buf)


def test_gui_process_never_loads_mupdf(tmp_path, pdf_a, pdf_b):
    """The GUI must do all PDF parsing through the worker."""
    out = tmp_path / "out.pdf"
    script = textwrap.dedent(f"""
        import os, sys
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        sys.path.insert(0, {os.path.abspath('src')!r})
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QApplication
        from pdfmerger.core import settings as sm
        sm.set_settings(QSettings({str(tmp_path / 's.ini')!r}, QSettings.Format.IniFormat))
        app = QApplication([])
        from pdfmerger.ui.main_window import MainWindow, ExportWorker
        from pdfmerger.core.quality import ExportOptions
        w = MainWindow(); w.show()
        w.open_files([{pdf_a!r}, {pdf_b!r}])
        img = None
        for _ in range(200):
            img = w.thumbs.get(w.model.page(0).source_id, 0, 128)
            if img is not None: break
            app.processEvents(); import time; time.sleep(0.02)
        docs = list(w.registry)
        ex = ExportWorker(w.model.pages, docs, {{}}, ExportOptions(), {str(out)!r})
        ex.run()
        w.close()
        print("THUMB", img is not None)
        print("MUPDF", any(m == "pymupdf" or m.startswith(("pymupdf.", "fitz")) for m in sys.modules))
    """)
    r = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=120)
    assert "THUMB True" in r.stdout, r.stdout + r.stderr
    assert "MUPDF False" in r.stdout, r.stdout + r.stderr
    assert page_labels(out) == ["A1", "A2", "A3", "B1", "B2"]
