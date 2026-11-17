import os
from datetime import datetime

import pymupdf
import pytest

from pdfmerger.core import exporter
from pdfmerger.core.exporter import export, parse_pdf_date, pdf_date
from pdfmerger.core.pages import PageRef
from pdfmerger.core.quality import EncryptionOptions, ExportOptions, apply_preset, detect_preset
from pdfmerger.core.sources import PasswordRequired, SourceRegistry, NotAPdf

from conftest import page_labels


@pytest.fixture
def reg():
    r = SourceRegistry()
    yield r
    r.close_all()


def refs(src, idx):
    return [PageRef(src.id, i) for i in idx]


def test_merge_reorder_delete_duplicate(reg, pdf_a, pdf_b, tmp_path):
    a = reg.add(pdf_a)
    b = reg.add(pdf_b)
    pages = [PageRef(b.id, 1), PageRef(a.id, 0), PageRef(a.id, 2),
             PageRef(a.id, 0), PageRef(b.id, 0)]  # A2 deleted, A1 duplicated
    out = tmp_path / "out.pdf"
    export(pages, reg, {}, ExportOptions(), str(out))
    assert page_labels(out) == ["B2", "A1", "A3", "A1", "B1"]


def test_consecutive_runs_grouped():
    pages = [PageRef(1, 0), PageRef(1, 1), PageRef(1, 2), PageRef(2, 0), PageRef(1, 3), PageRef(1, 1)]
    assert list(exporter._runs(pages)) == [(1, 0, 2), (2, 0, 0), (1, 3, 3), (1, 1, 1)]


def test_rotation(reg, tmp_path):
    from conftest import make_pdf
    p = make_pdf(tmp_path / "r.pdf", ["R1", "R2"], rotate=90)
    s = reg.add(p)
    out = tmp_path / "out.pdf"
    export([PageRef(s.id, 0, 90), PageRef(s.id, 1, 270)], reg, {}, ExportOptions(), str(out))
    doc = pymupdf.open(out)
    assert [pg.rotation for pg in doc] == [180, 0]
    doc.close()


def test_metadata_roundtrip(reg, pdf_a, tmp_path):
    s = reg.add(pdf_a)
    meta = {"title": "Título ñ", "author": "Me", "subject": "S", "keywords": "k1, k2",
            "creator": "C", "producer": "P",
            "creationDate": pdf_date(datetime(2024, 1, 2, 3, 4, 5))}
    out = tmp_path / "out.pdf"
    export(refs(s, [0]), reg, meta, ExportOptions(), str(out))
    doc = pymupdf.open(out)
    m = doc.metadata
    doc.close()
    for k in ("title", "author", "subject", "keywords", "creator", "producer"):
        assert m[k] == meta[k]
    assert parse_pdf_date(m["creationDate"]) == datetime(2024, 1, 2, 3, 4, 5)
    assert m["modDate"].startswith("D:")


def test_encrypted_input(reg, pdf_locked, tmp_path):
    with pytest.raises(PasswordRequired):
        reg.add(pdf_locked)
    asked = []

    def ask(path, retry):
        asked.append(retry)
        return "wrong" if not retry else "secret"

    s = reg.add(pdf_locked, ask_password=ask)
    assert asked == [False, True]
    out = tmp_path / "out.pdf"
    export(refs(s, [0]), reg, {}, ExportOptions(), str(out))
    assert page_labels(out) == ["L1"]


def test_cancel_password(reg, pdf_locked):
    with pytest.raises(PasswordRequired):
        reg.add(pdf_locked, ask_password=lambda p, r: None)
    assert len(reg) == 0


def test_not_a_pdf(reg, tmp_path):
    bad = tmp_path / "x.pdf"
    bad.write_text("hello")
    with pytest.raises(NotAPdf):
        reg.add(str(bad))


def test_encrypted_output(reg, pdf_a, tmp_path):
    s = reg.add(pdf_a)
    opts = ExportOptions(encryption=EncryptionOptions(user_password="u", owner_password="o",
                                                      allow_copy=False))
    out = tmp_path / "out.pdf"
    export(refs(s, [0, 1]), reg, {}, opts, str(out))
    doc = pymupdf.open(out)
    assert doc.needs_pass
    assert doc.authenticate("u")
    assert not (doc.permissions & pymupdf.PDF_PERM_COPY)
    doc.close()
    assert page_labels(out, "u") == ["A1", "A2"]


def test_quality_presets_reduce_size(reg, pdf_images, tmp_path):
    s = reg.add(pdf_images)
    pages = refs(s, [0, 1])
    sizes = {}
    for preset in ("original", "print", "screen"):
        out = tmp_path / f"{preset}.pdf"
        sizes[preset] = export(pages, reg, {}, apply_preset(ExportOptions(), preset), str(out))
        assert page_labels(out) == ["I1", "I2"]
    assert sizes["screen"] < sizes["print"] < sizes["original"]
    assert sizes["screen"] < sizes["original"] / 5


def test_preset_detection():
    o = ExportOptions()
    assert detect_preset(o) == "original"
    e = apply_preset(o, "ebook")
    assert detect_preset(e) == "ebook"
    e.jpeg_quality = 42
    assert detect_preset(e) == "custom"


def test_options_dict_roundtrip_excludes_passwords():
    o = apply_preset(ExportOptions(encryption=EncryptionOptions(user_password="x")), "screen")
    d = o.to_dict()
    assert "encryption" not in d
    # QSettings returns strings for everything on some platforms
    back = ExportOptions.from_dict({k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in d.items()})
    assert back == ExportOptions(**{**o.__dict__, "encryption": None})


def test_failed_save_leaves_no_file(reg, pdf_a, tmp_path, monkeypatch):
    s = reg.add(pdf_a)
    out = tmp_path / "out.pdf"

    # progress returns True for the "pages" stage, False (cancel) at "images"
    with pytest.raises(exporter.ExportCancelled):
        export(refs(s, [0]), reg, {}, ExportOptions(), str(out),
               progress=lambda d, t, st: st == "pages" or False)
    assert not out.exists()
    assert not [f for f in os.listdir(tmp_path) if f.endswith(".tmp")]


def test_empty_export_rejected(reg, tmp_path):
    with pytest.raises(ValueError):
        export([], reg, {}, ExportOptions(), str(tmp_path / "x.pdf"))


def test_cli_export(pdf_a, pdf_b, pdf_locked, tmp_path):
    from pdfmerger.cli import run
    out = tmp_path / "cli.pdf"
    log = tmp_path / "log.txt"
    pw = tmp_path / "pw.txt"
    pw.write_text("wrong\nsecret\n")
    rc = run(["x", "--export", str(out), "--preset", "screen", "--title", "CLI",
              "--input-password-file", str(pw), "--log", str(log), pdf_a, pdf_locked, pdf_b])
    assert rc == 0, log.read_text()
    assert page_labels(out) == ["A1", "A2", "A3", "L1", "B1", "B2"]
    doc = pymupdf.open(out)
    assert doc.metadata["title"] == "CLI"
    doc.close()
    assert run(["x", "--export", str(out)]) == 2


def test_cli_bad_arguments_are_logged(tmp_path, pdf_a):
    from pdfmerger.cli import run
    log = tmp_path / "log.txt"
    assert run(["x", "--export", str(tmp_path / "o.pdf"), "--preset", "nope",
                "--log", str(log), pdf_a]) == 2
    assert "error:" in log.read_text()


def test_cli_password_file_and_sanitize(pdf_a, tmp_path, monkeypatch):
    import io
    from pdfmerger.cli import run
    out = tmp_path / "enc.pdf"
    monkeypatch.setattr("sys.stdin", io.StringIO("s3cret\n"))
    assert run(["x", "--export", str(out), "--password-file", "-", "--sanitize", pdf_a]) == 0
    d = pymupdf.open(out)
    assert d.needs_pass and d.authenticate("s3cret")
    d.close()


def test_cli_refuses_plain_password_argument(pdf_a, tmp_path):
    from pdfmerger.cli import run
    assert run(["x", "--export", str(tmp_path / "o.pdf"), "--password", "x", pdf_a]) == 2


def test_cli_refuses_overwriting_input(pdf_a, tmp_path):
    from pdfmerger.cli import run
    before = open(pdf_a, "rb").read()
    assert run(["x", "--export", pdf_a, pdf_a]) == 1
    assert open(pdf_a, "rb").read() == before
