"""Undoable edits. Each command stores page-list snapshots (PageRefs are tiny)."""
from __future__ import annotations

from typing import Callable, Optional, Sequence

from PySide6.QtGui import QUndoCommand

from ..core.pages import PageRef


class PagesCommand(QUndoCommand):
    """Replace the page list; optionally run hooks (e.g. add/remove sources)."""

    def __init__(self, text: str, apply: Callable[[Sequence[PageRef], Sequence[int]], None],
                 before: Sequence[PageRef], after: Sequence[PageRef],
                 select_before: Sequence[int] = (), select_after: Sequence[int] = (),
                 on_redo: Optional[Callable[[], None]] = None,
                 on_undo: Optional[Callable[[], None]] = None):
        super().__init__(text)
        self._apply = apply
        self._before = list(before)
        self._after = list(after)
        self._sel_before = list(select_before)
        self._sel_after = list(select_after)
        self._on_redo = on_redo
        self._on_undo = on_undo

    def redo(self) -> None:
        if self._on_redo:
            self._on_redo()
        self._apply(self._after, self._sel_after)

    def undo(self) -> None:
        self._apply(self._before, self._sel_before)
        if self._on_undo:
            self._on_undo()
