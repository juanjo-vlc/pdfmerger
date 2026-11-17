"""Grid view of page thumbnails with drag & drop reordering."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPalette, QPen, QTransform
from PySide6.QtWidgets import (QAbstractItemView, QListView, QStyle, QStyledItemDelegate,
                               QStyleOptionViewItem)

from ..core.pages import PageRef
from ..core.thumbnails import ThumbnailService
from .page_model import ROW_MIME, PageRefRole

LABEL_H = 22
PAD = 8


class PageDelegate(QStyledItemDelegate):
    def __init__(self, view: "PageView", thumbs: ThumbnailService, color_for, parent=None):
        super().__init__(parent)
        self._view = view
        self._thumbs = thumbs
        self._color_for = color_for

    def sizeHint(self, option, index) -> QSize:
        s = self._view.thumb_size
        return QSize(s + 2 * PAD, s + 2 * PAD + LABEL_H)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        ref: PageRef = index.data(PageRefRole)
        if ref is None:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = option.rect
        pal = option.palette
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if selected:
            hl = QColor(pal.color(QPalette.ColorRole.Highlight))
            hl.setAlpha(70)
            painter.fillRect(r.adjusted(2, 2, -2, -2), hl)
            painter.setPen(QPen(pal.color(QPalette.ColorRole.Highlight), 2))
            painter.drawRoundedRect(r.adjusted(2, 2, -2, -2), 4, 4)

        s = self._view.thumb_size
        box = QRect(r.x() + PAD, r.y() + PAD, s, s)
        dpr = self._view.devicePixelRatioF()
        img = self._thumbs.get(ref.source_id, ref.page_index, int(s * dpr))
        if img is not None:
            if ref.rotation:
                img = img.transformed(QTransform().rotate(ref.rotation))
            target = QSize(img.width(), img.height()).scaled(box.size(), Qt.AspectRatioMode.KeepAspectRatio)
            tr = QRect(QPoint(0, 0), target)
            tr.moveCenter(box.center())
            painter.fillRect(tr.adjusted(2, 2, 2, 2), QColor(0, 0, 0, 40))   # shadow
            painter.drawImage(tr, img)
            frame = tr
        else:
            frame = QRect(0, 0, int(s * 0.707), s)
            if ref.rotation in (90, 270):
                frame = QRect(0, 0, s, int(s * 0.707))
            frame.moveCenter(box.center())
            painter.fillRect(frame, QColor(245, 245, 245))
            failed = self._thumbs.is_failed(ref.source_id, ref.page_index)
            painter.setPen(QColor(192, 57, 43) if failed else QColor(160, 160, 160))
            painter.drawText(frame, Qt.AlignmentFlag.AlignCenter, "⚠" if failed else "…")
        color = self._color_for(ref.source_id)
        painter.setPen(QPen(color, 3))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(frame.adjusted(-1, -1, 1, 1))

        # label: "<position>" plus source page in a source-colored chip
        label_rect = QRect(r.x() + PAD, r.y() + PAD + s + 2, s, LABEL_H - 4)
        painter.setPen(pal.color(QPalette.ColorRole.Text))
        f = painter.font()
        f.setBold(True)
        painter.setFont(f)
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         index.data(Qt.ItemDataRole.DisplayRole))
        f.setBold(False)
        painter.setFont(f)
        chip_text = f"p.{ref.page_index + 1}"
        if ref.rotation:
            chip_text += f" ↻{ref.rotation}°"
        fm = painter.fontMetrics()
        cw = fm.horizontalAdvance(chip_text) + 10
        chip = QRect(label_rect.right() - cw, label_rect.y() + 1, cw, label_rect.height() - 2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(chip, 6, 6)
        painter.setPen(QColor("white") if color.lightness() < 160 else QColor("black"))
        painter.drawText(chip, Qt.AlignmentFlag.AlignCenter, chip_text)
        painter.restore()


class PageView(QListView):
    zoomChanged = Signal(int)
    MIN_SIZE, MAX_SIZE = 80, 400

    def __init__(self, parent=None):
        super().__init__(parent)
        self.thumb_size = 160
        self._empty_text = ""
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setUniformItemSizes(True)
        self.setSpacing(4)
        self.setWrapping(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        # Static movement makes QListView route drops through the model
        # (dropMimeData) instead of moving icons freely; re-enable dragging after.
        self.setMovement(QListView.Movement.Static)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

    def set_empty_text(self, text: str) -> None:
        self._empty_text = text
        self.viewport().update()

    def set_thumb_size(self, size: int) -> None:
        size = max(self.MIN_SIZE, min(self.MAX_SIZE, int(size)))
        if size == self.thumb_size:
            return
        self.thumb_size = size
        self.scheduleDelayedItemsLayout()
        self.viewport().update()
        self.zoomChanged.emit(size)

    def wheelEvent(self, e):
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            step = 20 if e.angleDelta().y() > 0 else -20
            self.set_thumb_size(self.thumb_size + step)
            e.accept()
            return
        super().wheelEvent(e)

    def _foreign_rows(self, e) -> bool:
        """Row-move data is only meaningful when it comes from this very view."""
        return e.mimeData().hasFormat(ROW_MIME) and e.source() is not self

    def dragEnterEvent(self, e):
        if self._foreign_rows(e):
            e.ignore()
            return
        if e.mimeData().hasUrls() and e.source() is None:
            e.setDropAction(Qt.DropAction.CopyAction)
        super().dragEnterEvent(e)

    def dropEvent(self, e):
        if self._foreign_rows(e):
            e.ignore()
            return
        super().dropEvent(e)

    def dragMoveEvent(self, e):
        if self._foreign_rows(e):
            e.ignore()
            return
        super().dragMoveEvent(e)
        if e.mimeData().hasUrls() and e.source() is None:
            e.setDropAction(Qt.DropAction.CopyAction)
            e.accept()

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.model() is not None and self.model().rowCount() == 0 and self._empty_text:
            p = QPainter(self.viewport())
            p.setPen(self.palette().color(QPalette.ColorRole.PlaceholderText))
            f = p.font()
            f.setPointSizeF(f.pointSizeF() * 1.3)
            p.setFont(f)
            p.drawText(self.viewport().rect(), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                       self._empty_text)
