"""PDF date strings (no PyMuPDF import)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional


def pdf_date(dt: datetime) -> str:
    """Format a datetime as a PDF date string (D:YYYYMMDDHHmmSS+HH'mm')."""
    if dt.tzinfo is None:
        dt = dt.astimezone()
    off = dt.utcoffset()
    total = int(off.total_seconds()) if off is not None else 0
    sign = "+" if total >= 0 else "-"
    total = abs(total)
    return dt.strftime("D:%Y%m%d%H%M%S") + f"{sign}{total // 3600:02d}'{(total % 3600) // 60:02d}'"


def parse_pdf_date(value: str) -> Optional[datetime]:
    if not value:
        return None
    v = value[2:] if value.startswith("D:") else value
    digits = "".join(ch for ch in v[:14] if ch.isdigit())
    fmts = {14: "%Y%m%d%H%M%S", 12: "%Y%m%d%H%M", 8: "%Y%m%d", 6: "%Y%m", 4: "%Y"}
    fmt = fmts.get(len(digits))
    if not fmt:
        return None
    try:
        return datetime.strptime(digits, fmt)
    except ValueError:
        return None
