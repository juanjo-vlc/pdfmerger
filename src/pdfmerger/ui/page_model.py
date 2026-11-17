"""List model over the working document's PageRefs."""
from __future__ import annotations

import json
from typing import Callable, Optional, Sequence

from PySide6.QtCore import (QAbstractListModel, QByteArray, QMimeData, QModelIndex, Qt,
                            Signal)

from ..core.pages import PageRef
from .safe_text import tooltip

ROW_MIME = "application/x-pdfmerger-rows"
PageRefRole = Qt.ItemDataRole.UserRole + 1
SourceIdRole = Qt.ItemDataRole.UserRole + 2


class PageModel(QAbstractListModel):
    # emitted by drops; the main window turns them into undoable commands
    moveRequested = Signal(list, int)        # rows, destination row
    filesDropped = Signal(list, int)         # local paths, destination row

    def __init__(self, label_for: Callable[[PageRef], str], parent=None):
        super().__init__(parent)
        self._pages: list[PageRef] = []
        self._label_for = label_for

    # ---- data access -------------------------------------------------
    @property
    def pages(self) -> list[PageRef]:
        return list(self._pages)

    def set_pages(self, pages: Sequence[PageRef]) -> None:
        self.beginResetModel()
        self._pages = list(pages)
        self.endResetModel()

    def page(self, row: int) -> PageRef:
        return self._pages[row]

    def rows_for(self, source_id: int, page_index: int) -> list[int]:
        return [i for i, p in enumerate(self._pages)
                if p.source_id == source_id and p.page_index == page_index]

    def refresh_page(self, source_id: int, page_index: int) -> None:
        for r in self.rows_for(source_id, page_index):
            idx = self.index(r)
            self.dataChanged.emit(idx, idx, [Qt.ItemDataRole.DecorationRole])

    # ---- Qt model API --------------------------------------------------
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._pages)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._pages):
            return None
        ref = self._pages[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return str(index.row() + 1)
        if role == Qt.ItemDataRole.ToolTipRole:
            return tooltip(self._label_for(ref))
        if role == PageRefRole:
            return ref
        if role == SourceIdRole:
            return ref.source_id
        return None

    def flags(self, index: QModelIndex):
        base = Qt.ItemFlag.ItemIsDropEnabled
        if not index.isValid():
            return base
        return (base | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsDragEnabled)

    def supportedDropActions(self):
        return Qt.DropAction.MoveAction | Qt.DropAction.CopyAction

    def supportedDragActions(self):
        return Qt.DropAction.MoveAction

    def mimeTypes(self) -> list[str]:
        return [ROW_MIME, "text/uri-list"]

    def mimeData(self, indexes) -> QMimeData:
        rows = sorted({i.row() for i in indexes if i.isValid()})
        md = QMimeData()
        md.setData(ROW_MIME, QByteArray(json.dumps(rows).encode()))
        return md

    @staticmethod
    def _pdf_paths(md: QMimeData) -> list[str]:
        return [u.toLocalFile() for u in md.urls()
                if u.isLocalFile() and u.toLocalFile().lower().endswith(".pdf")]

    def canDropMimeData(self, md, action, row, column, parent) -> bool:
        return md.hasFormat(ROW_MIME) or bool(self._pdf_paths(md))

    def _dest_row(self, row: int, parent: QModelIndex) -> int:
        if row >= 0:
            return row
        if parent.isValid():
            return parent.row()
        return len(self._pages)

    def dropMimeData(self, md, action, row, column, parent) -> bool:
        dest = self._dest_row(row, parent)
        if md.hasFormat(ROW_MIME):
            try:
                rows = json.loads(bytes(md.data(ROW_MIME)).decode())
            except (ValueError, UnicodeDecodeError):
                return False
            if (not isinstance(rows, list) or not rows
                    or not all(type(r) is int and 0 <= r < len(self._pages) for r in rows)):
                return False
            self.moveRequested.emit(rows, dest)
            # Returning False stops the view from also removing the dragged rows;
            # the move is applied by the undoable command.
            return False
        paths = self._pdf_paths(md)
        if paths:
            self.filesDropped.emit(paths, dest)
            return False
        return False


def move_rows(pages: Sequence[PageRef], rows: Sequence[int], dest: int) -> tuple[list[PageRef], list[int]]:
    """Move ``rows`` (any order) so they start at ``dest`` (index in the original list).

    Returns the new list and the new row numbers of the moved items.
    """
    rows = sorted(set(r for r in rows if 0 <= r < len(pages)))
    if not rows:
        return list(pages), []
    moving = [pages[r] for r in rows]
    keep = [p for i, p in enumerate(pages) if i not in set(rows)]
    insert_at = dest - sum(1 for r in rows if r < dest)
    insert_at = max(0, min(insert_at, len(keep)))
    new = keep[:insert_at] + moving + keep[insert_at:]
    return new, list(range(insert_at, insert_at + len(moving)))
