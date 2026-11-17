"""Registry of opened source PDF documents."""
from __future__ import annotations

import itertools
import os
from dataclasses import dataclass, field
from typing import Callable, Optional

import pymupdf

from .errors import NotAPdf, PasswordRequired, UnsafePdf  # noqa: F401 (re-exported)
from .fileio import same_file  # noqa: F401 (re-exported)


# Safety limits for untrusted input. MuPDF is native code: refuse documents whose
# size alone could exhaust memory or make rendering/exporting hang.
MAX_FILE_BYTES = 2 * 1024 ** 3          # 2 GiB
MAX_PAGES = 10_000                      # per file
MAX_IMAGE_PIXELS = 400_000_000          # per embedded image (e.g. 20000 x 20000)
MAX_PAGE_POINTS = 14_400 * 4            # page side, in points (4x the PDF spec's 200 in)


def check_limits(doc: pymupdf.Document) -> None:
    if doc.page_count > MAX_PAGES:
        raise UnsafePdf(f"too many pages ({doc.page_count} > {MAX_PAGES})")
    for page in doc:
        r = page.rect
        if r.width > MAX_PAGE_POINTS or r.height > MAX_PAGE_POINTS or r.is_empty:
            raise UnsafePdf(f"page {page.number + 1} has an invalid size ({r.width:.0f} x {r.height:.0f} pt)")
    # Check the images the pages actually use. (Walking the whole object table instead
    # is a denial-of-service: a tiny file can declare object numbers in the millions.
    # Found by fuzzing.) Unreferenced images are never rendered or exported.
    seen: set[int] = set()
    for page in doc:
        try:
            images = page.get_images(full=True)
        except Exception:
            continue
        for img in images:
            xref, w, h = img[0], img[2], img[3]
            if xref in seen:
                continue
            seen.add(xref)
            if w < 0 or h < 0 or w * h > MAX_IMAGE_PIXELS:
                raise UnsafePdf(f"an embedded image is too large ({w} x {h} pixels)")


@dataclass
class Source:
    id: int
    path: str
    password: Optional[str]
    doc: pymupdf.Document = field(repr=False)
    page_count: int = 0   # cached so the GUI never touches ``doc`` during an export

    def __post_init__(self) -> None:
        if not self.page_count:
            self.page_count = self.doc.page_count

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    def open_copy(self) -> pymupdf.Document:
        """Open an independent handle (PyMuPDF documents are not thread-safe)."""
        doc = pymupdf.open(self.path)
        if doc.needs_pass:
            doc.authenticate(self.password or "")
        return doc


def open_pdf(path: str, password: Optional[str] = None) -> pymupdf.Document:
    try:
        size = os.path.getsize(path)
    except OSError as exc:
        raise NotAPdf(str(exc)) from exc
    if size > MAX_FILE_BYTES:
        raise UnsafePdf(f"file is too large ({size // 1024 ** 2} MB)")
    try:
        doc = pymupdf.open(path)
    except Exception as exc:  # pymupdf raises various types
        raise NotAPdf(str(exc)) from exc
    if not doc.is_pdf:
        doc.close()
        raise NotAPdf(f"{path} is not a PDF file")
    if doc.needs_pass:
        if not password or not doc.authenticate(password):
            doc.close()
            raise PasswordRequired(path)
    try:
        check_limits(doc)
    except Exception:
        doc.close()
        raise
    return doc


class SourceRegistry:
    def __init__(self) -> None:
        self._sources: dict[int, Source] = {}
        self._ids = itertools.count(1)

    def add(
        self,
        path: str,
        password: Optional[str] = None,
        ask_password: Optional[Callable[[str, bool], Optional[str]]] = None,
        source_id: Optional[int] = None,
    ) -> Source:
        """Open ``path``. If encrypted, ``ask_password(path, retry)`` is called
        until it returns a valid password or ``None`` (cancel)."""
        retry = False
        while True:
            try:
                doc = open_pdf(path, password)
                break
            except PasswordRequired:
                if ask_password is None:
                    raise
                password = ask_password(path, retry)
                retry = True
                if password is None:
                    raise
        sid = next(self._ids) if source_id is None else source_id
        old = self._sources.pop(sid, None)
        if old is not None:
            old.doc.close()
        src = Source(sid, os.path.abspath(path), password, doc)
        self._sources[src.id] = src
        return src

    def restore(self, src: Source) -> None:
        """Re-insert a previously removed source (used by undo)."""
        if src.doc.is_closed:
            src.doc = src.open_copy()
        self._sources[src.id] = src

    def remove(self, source_id: int) -> Source:
        return self._sources.pop(source_id)

    def get(self, source_id: int) -> Source:
        return self._sources[source_id]

    def __contains__(self, source_id: int) -> bool:
        return source_id in self._sources

    def __iter__(self):
        return iter(self._sources.values())

    def __len__(self) -> int:
        return len(self._sources)

    def close_all(self) -> None:
        for s in self._sources.values():
            s.doc.close()
        self._sources.clear()
