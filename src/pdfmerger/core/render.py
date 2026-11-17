"""Page rendering for thumbnails (runs in the worker)."""
from __future__ import annotations

import pymupdf

MAX_THUMB = 1024


def render_page(doc: pymupdf.Document, index: int, size: int) -> tuple[int, int, int, bytes]:
    """Render page ``index`` so its longer side is ``size`` px. Returns (w, h, stride, RGB)."""
    size = max(16, min(MAX_THUMB, int(size)))
    page = doc[index]
    rect = page.rect  # already accounts for the page's /Rotate
    scale = size / max(rect.width, rect.height, 1)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
    return pix.width, pix.height, pix.stride, bytes(pix.samples)
