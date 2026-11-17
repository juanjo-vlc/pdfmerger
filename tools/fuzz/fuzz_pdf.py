"""Coverage-guided fuzzing of the worker's PDF path (Atheris + libFuzzer).

Runs the same code the sandboxed worker runs on untrusted input:
open -> safety limits -> render thumbnails -> export (plain / sanitized / recompressed).

MuPDF *errors* on malformed files are expected (the worker reports them as "file could
not be opened"). What counts as a finding:
  * a crash, hang (-timeout) or memory blow-up (-rss_limit_mb) in MuPDF or our code
  * an export that is not a valid PDF or has the wrong number of pages
  * JavaScript that survives the "sanitize" option
Usage: tools/fuzz/run.sh [seconds]
"""
import sys

import atheris

with atheris.instrument_imports(include=["pdfmerger"]):
    from pdfmerger.core import exporter, render, sources
    from pdfmerger.core.errors import UnsafePdf
    from pdfmerger.core.pages import PageRef
    from pdfmerger.core.quality import ExportOptions, apply_preset

import pymupdf
from pymupdf import mupdf

pymupdf.TOOLS.mupdf_display_errors(False)
pymupdf.TOOLS.mupdf_display_warnings(False)

OPTIONS = [
    ExportOptions(),
    ExportOptions(sanitize=True),
    apply_preset(ExportOptions(), "screen"),
    ExportOptions(sanitize=True, garbage=4, clean=True),
]


class _Source:
    def __init__(self, doc):
        self.doc = doc
        self.path = "<fuzz>"


class _Registry:
    def __init__(self, doc):
        self._src = _Source(doc)

    def get(self, sid):
        return self._src


# JavaScript only runs through an action dictionary: << /S /JavaScript /JS ... >>.
# Walk the *parsed* objects: text matching gives false positives for names like
# "/JavaScript95" or for strings that merely contain "<</S/JavaScript/JS ...>>".
def _obj_has_js(obj, depth=0) -> bool:
    if depth > 64 or mupdf.pdf_is_indirect(obj):   # each indirect object is checked on its own
        return False
    if mupdf.pdf_is_dict(obj):
        for i in range(mupdf.pdf_dict_len(obj)):
            key = mupdf.pdf_to_name(mupdf.pdf_dict_get_key(obj, i))
            val = mupdf.pdf_dict_get_val(obj, i)
            if key == "JS":
                return True
            if key == "S" and mupdf.pdf_is_name(val) and mupdf.pdf_to_name(val) == "JavaScript":
                return True
            if _obj_has_js(val, depth + 1):
                return True
    elif mupdf.pdf_is_array(obj):
        for i in range(mupdf.pdf_array_len(obj)):
            if _obj_has_js(mupdf.pdf_array_get(obj, i), depth + 1):
                return True
    return False


def _has_javascript(doc) -> bool:
    pdf = mupdf.pdf_document_from_fz_document(doc.this)
    for xref in range(1, doc.xref_length()):
        try:
            obj = mupdf.pdf_load_object(pdf, xref)
        except Exception:
            continue
        if _obj_has_js(obj):
            return True
    return False


def TestOneInput(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    mode = fdp.ConsumeIntInRange(0, len(OPTIONS) - 1)
    pdf = fdp.ConsumeBytes(fdp.remaining_bytes())
    try:
        doc = pymupdf.open(stream=pdf, filetype="pdf")
    except Exception:
        return
    try:
        if doc.needs_pass or not doc.is_pdf:
            return
        try:
            sources.check_limits(doc)
        except UnsafePdf:
            return
        except Exception:
            return          # malformed structure: the worker reports "not a valid PDF"
        n = min(doc.page_count, 3)
        for i in range(n):
            try:
                render.render_page(doc, i, 64)
            except Exception:
                pass        # shown as a failed thumbnail
        if n == 0:
            return
        opts = OPTIONS[mode]
        pages = [PageRef(1, i, 90 * (i % 4)) for i in range(n)]
        try:
            out = exporter.export_bytes(pages, _Registry(doc), {"title": "fuzz"}, opts)
        except exporter.DamagedOutput:
            return          # refused cleanly: the user gets a clear error, not a broken file
        except Exception:
            return          # reported to the user as an export error
        # --- invariants on what we produce -----------------------------------------
        result = pymupdf.open(stream=out, filetype="pdf")
        try:
            if not exporter.verify_output(out, n):
                raise AssertionError("export is not a well-formed PDF")
            if opts.sanitize and _has_javascript(result):
                raise AssertionError("JavaScript survived sanitize")
        finally:
            result.close()
    finally:
        doc.close()


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
