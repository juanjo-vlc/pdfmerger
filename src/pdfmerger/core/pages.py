"""Pure data describing a page in the working document."""
from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class PageRef:
    """A reference to one page of a source document.

    ``rotation`` is the extra clockwise rotation (0/90/180/270) the user applied
    on top of the page's own /Rotate value.
    """

    source_id: int
    page_index: int
    rotation: int = 0

    def rotated(self, degrees: int) -> "PageRef":
        return replace(self, rotation=(self.rotation + degrees) % 360)
