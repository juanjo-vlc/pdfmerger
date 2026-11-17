"""Tests for the security hardening (limits, sanitize, encryption, same-file checks)."""
import os

import pymupdf
import pytest

from pdfmerger.core import sources
from pdfmerger.core.exporter import export
from pdfmerger.core.pages import PageRef
from pdfmerger.core.quality import EncryptionOptions, ExportOptions
from pdfmerger.core.sources import SourceRegistry, UnsafePdf, same_file


@pytest.fixture
def reg():
    r = SourceRegistry()
    yield r
    r.close_all()


def active_pdf(path):
    """A page with a link, a form field, JavaScript, an attachment and XMP metadata."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "ACTIVE")
    page.insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(72, 80, 200, 100),
                      "uri": "https://example.invalid/"})
    w = pymupdf.Widget()
    w.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
    w.field_name = "name"
    w.rect = pymupdf.Rect(72, 120, 250, 140)
    w.script = "app.alert('field')"            # JavaScript on a form field
    page.add_widget(w)
    js_page = doc.get_new_xref()                 # JavaScript run when the page opens
    doc.update_object(js_page, "<< /S /JavaScript /JS (app.alert('page')) >>")
    doc.xref_set_key(page.xref, "AA", f"<< /O {js_page} 0 R >>")
    doc.embfile_add("payload.txt", b"hello")
    cat = doc.pdf_catalog()
    js = doc.get_new_xref()
    doc.update_object(js, "<< /S /JavaScript /JS (app.alert(1)) >>")
    doc.xref_set_key(cat, "OpenAction", f"{js} 0 R")
    doc.set_xml_metadata("<x:xmpmeta xmlns:x='adobe:ns:meta/'>secret-author</x:xmpmeta>")
    doc.save(str(path))
    doc.close()
    return str(path)


def has_javascript(doc):
    return any("/JavaScript" in doc.xref_object(x) for x in range(1, doc.xref_length())
               if doc.xref_object(x))


def test_sanitize_removes_active_content(reg, tmp_path):
    src = reg.add(active_pdf(tmp_path / "in.pdf"))
    plain, clean = tmp_path / "plain.pdf", tmp_path / "clean.pdf"
    export([PageRef(src.id, 0)], reg, {}, ExportOptions(), str(plain))
    export([PageRef(src.id, 0)], reg, {}, ExportOptions(sanitize=True), str(clean))

    d = pymupdf.open(plain)
    # without sanitize, page-level active content is carried into the output
    assert d[0].get_links() and list(d[0].widgets())
    assert has_javascript(d)
    d.close()

    d = pymupdf.open(clean)
    assert d[0].get_text().strip() == "ACTIVE"
    assert not d[0].get_links()
    assert not list(d[0].widgets())
    assert d.embfile_count() == 0
    assert not has_javascript(d)
    assert "secret-author" not in (d.get_xml_metadata() or "")
    d.close()


def test_open_password_only_gets_random_owner_password(reg, pdf_a, tmp_path):
    s = reg.add(pdf_a)
    out = tmp_path / "out.pdf"
    opts = ExportOptions(encryption=EncryptionOptions(user_password="u", allow_copy=False))
    export([PageRef(s.id, 0)], reg, {}, opts, str(out))
    d = pymupdf.open(out)
    rc = d.authenticate("u")
    assert rc & 2 and not rc & 4            # user access, but not owner access
    assert not d.permissions & pymupdf.PDF_PERM_COPY
    d.close()


def test_refuses_to_overwrite_input(reg, pdf_a):
    s = reg.add(pdf_a)
    before = open(pdf_a, "rb").read()
    with pytest.raises(ValueError):
        export([PageRef(s.id, 0)], reg, {}, ExportOptions(), pdf_a)
    assert open(pdf_a, "rb").read() == before


def test_same_file_through_other_spelling(tmp_path, pdf_a):
    other = os.path.join(str(tmp_path), ".", os.path.basename(pdf_a))
    assert same_file(pdf_a, other)
    assert not same_file(pdf_a, str(tmp_path / "nope.pdf"))


def test_page_limit(reg, tmp_path, monkeypatch):
    from conftest import make_pdf
    p = make_pdf(tmp_path / "many.pdf", ["1", "2", "3"])
    monkeypatch.setattr(sources, "MAX_PAGES", 2)
    with pytest.raises(UnsafePdf):
        reg.add(p)


def test_file_size_limit(reg, pdf_a, monkeypatch):
    monkeypatch.setattr(sources, "MAX_FILE_BYTES", 10)
    with pytest.raises(UnsafePdf):
        reg.add(pdf_a)


def test_declared_image_size_limit(reg, tmp_path):
    # An image used by the page that *claims* to be 100000 x 100000 pixels
    # (a decompression bomb): refused before anything is decoded.
    doc = pymupdf.open()
    page = doc.new_page()
    pix = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 4, 4), False)
    xref = page.insert_image(pymupdf.Rect(0, 0, 100, 100), pixmap=pix)
    doc.xref_set_key(xref, "Width", "100000")
    doc.xref_set_key(xref, "Height", "100000")
    path = tmp_path / "bomb.pdf"
    doc.save(str(path))
    doc.close()
    with pytest.raises(UnsafePdf):
        reg.add(str(path))


def test_settings_probe_does_not_follow_symlinks(tmp_path):
    from pdfmerger.core.settings import _is_writable_dir
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me")
    app = tmp_path / "app"
    app.mkdir()
    for pid_guess in range(os.getpid() - 2, os.getpid() + 3):   # old predictable names
        try:
            os.symlink(victim, app / f".write_test_{pid_guess}")
        except OSError:
            pytest.skip("symlinks not available")
    assert _is_writable_dir(str(app))
    assert victim.read_text() == "keep me"


def test_huge_object_numbers_are_fast(reg, tmp_path):
    """Regression (found by fuzzing): a tiny file declaring object 4000943 made the
    limits check walk millions of empty object slots."""
    import time
    path = tmp_path / "sparse.pdf"
    path.write_bytes(b"%PDF-1.7\n4000943 0 obj\n<</Type/Catalog/Pages 2 0 R>>\nendobj\n"
                     b"trailer<</Root 4000943 0 R>>\n%%EOF\n")
    start = time.monotonic()
    try:
        reg.add(str(path))
    except Exception:
        pass
    assert time.monotonic() - start < 2


def test_damaged_input_still_gives_clean_output(reg, tmp_path):
    """Regression (found by fuzzing): MuPDF copied a damaged object from this input into
    an output it could not read back cleanly. Exports are now verified and rebuilt."""
    from pdfmerger.core.exporter import verify_output
    from pdfmerger.core.quality import ExportOptions as EO
    src = os.path.join(os.path.dirname(__file__), "data", "damaged-object.pdf")
    s = reg.add(src)
    for opts in (EO(), EO(sanitize=True), EO(use_objstms=False),
                 EO(encryption=EncryptionOptions(user_password="pw"))):
        out = tmp_path / "out.pdf"
        export([PageRef(s.id, 0)], reg, {}, opts, str(out))
        data = out.read_bytes()
        if opts.encryption:
            d = pymupdf.open(stream=data, filetype="pdf")
            assert d.authenticate("pw")
            assert d.page_count == 1 and not d.is_repaired
            d.close()
        else:
            assert verify_output(data, 1)
