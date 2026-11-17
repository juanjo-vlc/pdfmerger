"""Build and save the output PDF from a list of PageRefs."""
from __future__ import annotations

import os
import secrets
from datetime import datetime
from typing import Callable, Iterable, Optional, Sequence

import pymupdf

from .pages import PageRef
from .quality import ExportOptions
from .errors import ExportCancelled
from .fileio import same_file, write_atomic
from .pdfdates import parse_pdf_date, pdf_date  # noqa: F401 (re-exported)
from .sources import SourceRegistry

METADATA_KEYS = ("title", "author", "subject", "keywords", "creator", "producer",
                 "creationDate", "modDate")

ProgressCb = Callable[[int, int, str], bool]
"""progress(done, total, stage) -> False to cancel."""


def _runs(pages: Sequence[PageRef]) -> Iterable[tuple[int, int, int]]:
    """Group consecutive pages of the same source into (source_id, first, last)."""
    i = 0
    n = len(pages)
    while i < n:
        start = pages[i]
        j = i
        while (j + 1 < n and pages[j + 1].source_id == start.source_id
               and pages[j + 1].page_index == pages[j].page_index + 1):
            j += 1
        yield start.source_id, start.page_index, pages[j].page_index
        i = j + 1


def build_document(pages: Sequence[PageRef], registry: SourceRegistry,
                   progress: Optional[ProgressCb] = None, sanitize: bool = False) -> pymupdf.Document:
    if not pages:
        raise ValueError("No pages to export")
    out = pymupdf.open()
    total = len(pages)
    done = 0
    for source_id, first, last in _runs(pages):
        src = registry.get(source_id).doc
        if sanitize:
            out.insert_pdf(src, from_page=first, to_page=last, links=False, widgets=False)
        else:
            out.insert_pdf(src, from_page=first, to_page=last)
        done += last - first + 1
        if progress and progress(done, total, "pages") is False:
            out.close()
            raise ExportCancelled()
    for i, ref in enumerate(pages):
        if ref.rotation:
            page = out[i]
            page.set_rotation((page.rotation + ref.rotation) % 360)
    return out


def sanitize_document(doc: pymupdf.Document) -> None:
    """Remove active and hidden content that may come from untrusted inputs."""
    doc.scrub(attached_files=True, embedded_files=True, javascript=True, remove_links=True,
              xml_metadata=True, thumbnails=True, reset_fields=True, reset_responses=False,
              metadata=False, clean_pages=False, hidden_text=False, redactions=False)
    for xref in range(1, doc.xref_length()):      # actions not covered by scrub
        for key in ("AA", "OpenAction"):
            try:
                if doc.xref_get_key(xref, key)[0] != "null":
                    doc.xref_set_key(xref, key, "null")
            except Exception:
                pass


def apply_metadata(doc: pymupdf.Document, metadata: dict) -> None:
    meta = {k: (metadata.get(k) or "") for k in METADATA_KEYS}
    if not meta["modDate"]:
        meta["modDate"] = pdf_date(datetime.now())
    if not meta["creationDate"]:
        meta["creationDate"] = meta["modDate"]
    doc.set_metadata(meta)


def apply_quality(doc: pymupdf.Document, opts: ExportOptions) -> None:
    if not opts.rewrites_images:
        return
    dpi_threshold = dpi_target = 0
    if opts.downsample and opts.dpi_target > 0:
        dpi_target = opts.dpi_target
        dpi_threshold = max(opts.dpi_threshold, dpi_target + 1)
    quality = max(1, min(100, opts.jpeg_quality)) if opts.recompress else 0
    if not dpi_threshold and not quality:
        return
    doc.rewrite_images(
        dpi_threshold=dpi_threshold or None,
        dpi_target=dpi_target,
        quality=quality,
        lossy=True,
        lossless=opts.include_lossless_images,
        bitonal=opts.include_bitonal_images,
        color=True,
        gray=True,
    )


def save_kwargs(opts: ExportOptions) -> dict:
    kw = dict(
        garbage=max(0, min(4, opts.garbage)),
        deflate=opts.deflate,
        deflate_images=opts.deflate_images,
        deflate_fonts=opts.deflate_fonts,
        clean=opts.clean,
        use_objstms=opts.use_objstms,
    )
    enc = opts.encryption
    if enc and (enc.user_password or enc.owner_password):
        perm = pymupdf.PDF_PERM_ACCESSIBILITY
        if enc.allow_print:
            perm |= pymupdf.PDF_PERM_PRINT | pymupdf.PDF_PERM_PRINT_HQ
        if enc.allow_copy:
            perm |= pymupdf.PDF_PERM_COPY
        if enc.allow_modify:
            perm |= pymupdf.PDF_PERM_MODIFY | pymupdf.PDF_PERM_ASSEMBLE
        if enc.allow_annotate:
            perm |= pymupdf.PDF_PERM_ANNOTATE | pymupdf.PDF_PERM_FORM
        # Without a separate owner password, anyone who can open the file could lift
        # the restrictions, so use an unguessable one.
        owner = enc.owner_password or secrets.token_urlsafe(24)
        kw.update(
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            owner_pw=owner,
            user_pw=enc.user_password,
            permissions=perm,
        )
    return kw


class DamagedOutput(Exception):
    """MuPDF could not write a clean file from the (damaged) inputs."""


def verify_output(data: bytes, expected_pages: int) -> bool:
    """True if ``data`` is a well-formed PDF: no repair needed, every object readable and
    the page count right. (Fuzzing showed MuPDF can copy a damaged input object into an
    output it then cannot read back cleanly.)"""
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception:
        return False
    try:
        if doc.needs_pass:
            return True     # encrypted output: structure was verified before encryption
        first = doc.page_count
        if doc.is_repaired or first != expected_pages or doc.page_count != first:
            return False
        for xref in range(1, doc.xref_length()):
            try:
                doc.xref_object(xref, compressed=True)
            except Exception:
                return False
        return not doc.is_repaired
    finally:
        doc.close()


def _save_verified(doc: pymupdf.Document, opts: ExportOptions, pages: int) -> bytes:
    kwargs = save_kwargs(opts)
    plain = {k: v for k, v in kwargs.items()
             if k not in ("encryption", "owner_pw", "user_pw", "permissions")}
    attempts = [plain]
    if plain.get("use_objstms"):
        attempts.append({**plain, "use_objstms": False})
    for attempt in attempts:
        data = doc.tobytes(**attempt)
        if verify_output(data, pages):
            break
        # let MuPDF repair its own output, then write that again
        try:
            repaired = pymupdf.open(stream=data, filetype="pdf")
            data = repaired.tobytes(**{**attempt, "garbage": max(attempt.get("garbage", 0), 3)})
            repaired.close()
        except Exception:
            continue
        if verify_output(data, pages):
            break
    else:
        raise DamagedOutput("Some input pages contain damaged data that could not be copied "
                            "cleanly. Try exporting without those pages.")
    if "encryption" in kwargs:      # encrypt only the verified result
        clean = pymupdf.open(stream=data, filetype="pdf")
        try:
            data = clean.tobytes(**{**kwargs, "garbage": 0})
        finally:
            clean.close()
    return data


def export_bytes(pages: Sequence[PageRef], registry: SourceRegistry, metadata: dict,
                 opts: ExportOptions, progress: Optional[ProgressCb] = None) -> bytes:
    """Build the output PDF in memory (used by the sandboxed worker)."""
    def step(stage: str) -> None:
        if progress and progress(len(pages), len(pages), stage) is False:
            raise ExportCancelled()

    doc = build_document(pages, registry, progress, sanitize=opts.sanitize)
    try:
        if opts.sanitize:
            sanitize_document(doc)
        apply_metadata(doc, metadata)
        step("images")
        apply_quality(doc, opts)
        step("saving")
        return _save_verified(doc, opts, len(pages))
    finally:
        doc.close()


def export(pages: Sequence[PageRef], registry: SourceRegistry, metadata: dict,
           opts: ExportOptions, path: str, progress: Optional[ProgressCb] = None) -> int:
    """Write the output PDF atomically to ``path``. Returns the file size."""
    if os.path.exists(path) and any(same_file(path, registry.get(sid).path)
                                    for sid in {p.source_id for p in pages}):
        raise ValueError("The output file is one of the input files")
    return write_atomic(path, export_bytes(pages, registry, metadata, opts, progress))
