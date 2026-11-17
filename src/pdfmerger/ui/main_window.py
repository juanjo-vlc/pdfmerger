"""Main application window."""
from __future__ import annotations

import os
from typing import Optional, Sequence

from PySide6.QtCore import QSize, Qt, QThread, QTimer, QUrl, Signal, QItemSelectionModel
from PySide6.QtGui import (QAction, QColor, QDesktopServices, QIcon, QKeySequence, QPainter,
                           QPixmap, QUndoStack)
from PySide6.QtWidgets import (QAbstractItemView, QDockWidget, QFileDialog, QHBoxLayout,
                               QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
                               QProgressDialog, QPushButton, QSlider, QStyle, QToolBar,
                               QVBoxLayout, QWidget)

from .. import APP_NAME, __version__
from ..core.documents import DocInfo, DocumentStore
from ..core.errors import (ExportCancelled, NotAPdf, PasswordRequired, UnsafePdf,
                           WorkerCrashed)
from ..core.fileio import same_file, write_atomic
from ..core.pages import PageRef
from ..core.quality import ExportOptions
from ..core.settings import settings
from ..core.thumbnails import ThumbnailService
from ..core.worker_client import EXPORT_MEMORY, WorkerClient
from .commands import PagesCommand
from .export_dialog import ExportDialog
from .language_menu import build_language_menu
from .page_model import PageModel, move_rows
from .page_view import PageDelegate, PageView
from .password_dialog import PasswordDialog
from .properties_dialog import PropertiesDialog
from . import safe_text

SOURCE_COLORS = ["#2e86de", "#e67e22", "#27ae60", "#8e44ad", "#c0392b", "#16a085",
                 "#d35400", "#2c3e50", "#f1c40f", "#7f8c8d"]


def human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"


class ExportWorker(QThread):
    """Runs one export in a fresh, short-lived sandboxed worker; cancel = kill it."""
    progress = Signal(int, int, str)
    finished_ok = Signal(int)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, pages, docs: list[DocInfo], metadata, opts, path, parent=None):
        super().__init__(parent)
        self._pages = list(pages)
        self._docs = list(docs)
        self._metadata = dict(metadata)
        self._opts = opts
        self._path = path
        self._cancel = False
        self._client = WorkerClient(memory_limit=EXPORT_MEMORY)

    def cancel(self) -> None:
        self._cancel = True
        self._client.kill()

    def run(self) -> None:
        try:
            for d in self._docs:
                self._client.open(d.id, d.path, d.password)
            data = self._client.export(self._pages, self._metadata, self._opts,
                                       progress=lambda *a: self.progress.emit(*a))
            if self._cancel:
                raise ExportCancelled()
            size = write_atomic(self._path, data)
            self.finished_ok.emit(size)
        except (ExportCancelled, WorkerCrashed) as exc:
            if self._cancel:
                self.cancelled.emit()
            else:
                self.failed.emit(str(exc))
        except Exception as exc:  # report anything to the user
            self.failed.emit(str(exc))
        finally:
            self._client.shutdown()


class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(APP_NAME)
        self.setAcceptDrops(True)
        self.client = WorkerClient()
        self.registry = DocumentStore(self.client)
        self.thumbs = ThumbnailService(self.client, self)
        self.undo = QUndoStack(self)
        self.metadata: dict = {"producer": f"{APP_NAME} {__version__}"}
        self._metadata_edited = False
        self._export_worker: Optional[ExportWorker] = None

        self.model = PageModel(self._label_for, self)
        self.view = PageView(self)
        self.view.setModel(self.model)
        self.view.setItemDelegate(PageDelegate(self.view, self.thumbs, self._color_for, self.view))
        self.view.set_empty_text(self.tr("Drop PDF files here\nor use File ▸ Open (Ctrl+O)"))
        self.setCentralWidget(self.view)

        self.thumbs.ready.connect(self.model.refresh_page)
        self.model.moveRequested.connect(self._move_rows)
        self.model.filesDropped.connect(self.open_files)
        self.view.selectionModel().selectionChanged.connect(self._update_actions)
        self.model.modelReset.connect(self._update_actions)
        self.undo.indexChanged.connect(self._update_actions)
        self.view.zoomChanged.connect(self._zoom_changed)

        self._build_actions()
        self._build_sources_dock()
        self._build_statusbar()
        self._restore_settings()
        self._update_actions()

    # ------------------------------------------------------------------ UI setup
    def _icon(self, std: QStyle.StandardPixmap) -> QIcon:
        return self.style().standardIcon(std)

    def _action(self, text, slot, shortcut=None, icon=None, tip=None) -> QAction:
        a = QAction(text, self)
        if icon is not None:
            a.setIcon(icon if isinstance(icon, QIcon) else self._icon(icon))
        if shortcut:
            if isinstance(shortcut, (list, tuple)):
                a.setShortcuts([QKeySequence(s) for s in shortcut])
            else:
                a.setShortcut(QKeySequence(shortcut))
        if tip:
            a.setToolTip(tip)
        a.triggered.connect(slot)
        return a

    def _build_actions(self) -> None:
        SP = QStyle.StandardPixmap
        self.act_open = self._action(self.tr("&Open PDF files…"), self.open_dialog,
                                     QKeySequence.StandardKey.Open, SP.SP_DialogOpenButton)
        self.act_export = self._action(self.tr("&Export PDF…"), lambda: self.export_dialog(False),
                                       "Ctrl+S", SP.SP_DialogSaveButton)
        self.act_export_sel = self._action(self.tr("Export &selected pages…"),
                                           lambda: self.export_dialog(True), "Ctrl+Shift+S")
        self.act_props = self._action(self.tr("Document &properties…"), self.edit_properties,
                                      "Ctrl+I", SP.SP_FileDialogInfoView)
        self.act_clear = self._action(self.tr("&Close all files"), self.close_all, None,
                                      SP.SP_DialogResetButton)
        self.act_quit = self._action(self.tr("&Quit"), self.close, QKeySequence.StandardKey.Quit)

        self.act_undo = self._action(self.tr("&Undo"), self.undo.undo,
                                     QKeySequence.StandardKey.Undo, SP.SP_ArrowBack)
        self.act_redo = self._action(self.tr("&Redo"), self.undo.redo,
                                     [QKeySequence(QKeySequence.StandardKey.Redo), QKeySequence("Ctrl+Y")],
                                     SP.SP_ArrowForward)
        self.undo.canUndoChanged.connect(self.act_undo.setEnabled)
        self.undo.canRedoChanged.connect(self.act_redo.setEnabled)
        self.undo.undoTextChanged.connect(
            lambda t: self.act_undo.setToolTip(safe_text.tooltip(self.tr("Undo: {0}").format(t)) if t else self.tr("Undo")))
        self.undo.redoTextChanged.connect(
            lambda t: self.act_redo.setToolTip(safe_text.tooltip(self.tr("Redo: {0}").format(t)) if t else self.tr("Redo")))
        self.act_undo.setEnabled(False)
        self.act_redo.setEnabled(False)
        self.act_select_all = self._action(self.tr("Select &all"), self.view.selectAll,
                                           QKeySequence.StandardKey.SelectAll)
        self.act_delete = self._action(self.tr("&Delete pages"), self.delete_selected,
                                       QKeySequence.StandardKey.Delete, SP.SP_TrashIcon)
        self.act_dup = self._action(self.tr("D&uplicate pages"), self.duplicate_selected, "Ctrl+D",
                                    SP.SP_FileDialogNewFolder)
        self.act_rot_l = self._action(self.tr("Rotate &left"), lambda: self.rotate_selected(270),
                                      "Ctrl+Shift+R", self._text_icon("↺"))
        self.act_rot_r = self._action(self.tr("Rotate &right"), lambda: self.rotate_selected(90),
                                      "Ctrl+R", self._text_icon("↻"))
        self.act_up = self._action(self.tr("Move &earlier"), lambda: self.move_selected(-1),
                                   "Ctrl+Up", SP.SP_ArrowUp)
        self.act_down = self._action(self.tr("Move la&ter"), lambda: self.move_selected(1),
                                     "Ctrl+Down", SP.SP_ArrowDown)
        self.act_first = self._action(self.tr("Move to &beginning"), lambda: self.move_selected_to(0),
                                      "Ctrl+Home")
        self.act_last = self._action(self.tr("Move to e&nd"), lambda: self.move_selected_to(None),
                                     "Ctrl+End")
        self.act_reverse = self._action(self.tr("Re&verse order"), self.reverse_selected)

        self.act_zoom_in = self._action(self.tr("Zoom &in"), lambda: self.view.set_thumb_size(self.view.thumb_size + 20),
                                        QKeySequence.StandardKey.ZoomIn)
        self.act_zoom_out = self._action(self.tr("Zoom &out"), lambda: self.view.set_thumb_size(self.view.thumb_size - 20),
                                         QKeySequence.StandardKey.ZoomOut)
        self.act_about = self._action(self.tr("&About…"), self.about)

        mb = self.menuBar()
        m = mb.addMenu(self.tr("&File"))
        for a in (self.act_open, self.act_clear, None, self.act_props, None, self.act_export,
                  self.act_export_sel, None, self.act_quit):
            m.addSeparator() if a is None else m.addAction(a)
        m = mb.addMenu(self.tr("&Edit"))
        for a in (self.act_undo, self.act_redo, None, self.act_select_all, None, self.act_rot_l,
                  self.act_rot_r, self.act_dup, self.act_delete, None, self.act_up, self.act_down,
                  self.act_first, self.act_last, self.act_reverse):
            m.addSeparator() if a is None else m.addAction(a)
        m = mb.addMenu(self.tr("&View"))
        m.addAction(self.act_zoom_in)
        m.addAction(self.act_zoom_out)
        m.addSeparator()
        self.view_menu = m
        m.addMenu(build_language_menu(self))
        m = mb.addMenu(self.tr("&Help"))
        m.addAction(self.act_about)

        short = {self.act_open: self.tr("Open"), self.act_export: self.tr("Export"),
                 self.act_undo: self.tr("Undo"), self.act_redo: self.tr("Redo"),
                 self.act_rot_l: self.tr("Left"), self.act_rot_r: self.tr("Right"),
                 self.act_dup: self.tr("Duplicate"), self.act_delete: self.tr("Delete"),
                 self.act_up: self.tr("Earlier"), self.act_down: self.tr("Later"),
                 self.act_props: self.tr("Properties")}
        for act, text in short.items():
            act.setIconText(text)
            act.setToolTip(act.text().replace("&", "").rstrip("…") + (
                f" ({act.shortcut().toString(QKeySequence.SequenceFormat.NativeText)})"
                if not act.shortcut().isEmpty() else ""))
        tb = QToolBar(self.tr("Main toolbar"), self)
        tb.setObjectName("main_toolbar")
        tb.setIconSize(QSize(22, 22))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        for a in (self.act_open, self.act_export, None, self.act_undo, self.act_redo, None,
                  self.act_rot_l, self.act_rot_r, self.act_dup, self.act_delete, None,
                  self.act_up, self.act_down, None, self.act_props):
            tb.addSeparator() if a is None else tb.addAction(a)
        self.addToolBar(tb)

        # context menu on pages
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        for a in (self.act_rot_l, self.act_rot_r, self.act_dup, self.act_delete):
            self.view.addAction(a)
        sep = QAction(self)
        sep.setSeparator(True)
        self.view.addAction(sep)
        for a in (self.act_first, self.act_last, self.act_reverse, self.act_export_sel):
            self.view.addAction(a)

    def _text_icon(self, glyph: str) -> QIcon:
        pm = QPixmap(48, 48)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        f = p.font()
        f.setPixelSize(40)
        f.setBold(True)
        p.setFont(f)
        p.setPen(self.palette().color(self.foregroundRole()))
        p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, glyph)
        p.end()
        return QIcon(pm)

    def _build_sources_dock(self) -> None:
        dock = QDockWidget(self.tr("Files"), self)
        dock.setObjectName("sources_dock")
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable
                         | QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(4, 4, 4, 4)
        self.sources_list = QListWidget()
        self.sources_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.sources_list.itemDoubleClicked.connect(self._select_source_pages)
        self.sources_list.currentRowChanged.connect(lambda _: self._update_actions())
        v.addWidget(self.sources_list)
        h = QHBoxLayout()
        self.btn_add = QPushButton(self.tr("Add…"))
        self.btn_add.clicked.connect(self.open_dialog)
        self.btn_select_src = QPushButton(self.tr("Select pages"))
        self.btn_select_src.clicked.connect(lambda: self._select_source_pages(self.sources_list.currentItem()))
        self.btn_remove = QPushButton(self.tr("Remove"))
        self.btn_remove.clicked.connect(self.remove_current_source)
        for b in (self.btn_add, self.btn_select_src, self.btn_remove):
            h.addWidget(b)
        v.addLayout(h)
        dock.setWidget(w)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
        self.view_menu.insertAction(self.act_zoom_in, dock.toggleViewAction())

    def _build_statusbar(self) -> None:
        sb = self.statusBar()
        self.lbl_count = QLabel()
        sb.addPermanentWidget(self.lbl_count)
        self.zoom = QSlider(Qt.Orientation.Horizontal)
        self.zoom.setRange(PageView.MIN_SIZE, PageView.MAX_SIZE)
        self.zoom.setFixedWidth(140)
        self.zoom.setToolTip(self.tr("Thumbnail size (Ctrl + mouse wheel)"))
        self.zoom.setValue(self.view.thumb_size)
        self.zoom.valueChanged.connect(self.view.set_thumb_size)
        sb.addPermanentWidget(self.zoom)

    # ------------------------------------------------------------------ helpers
    def _color_for(self, source_id: int) -> QColor:
        return QColor(SOURCE_COLORS[(source_id - 1) % len(SOURCE_COLORS)])

    def _label_for(self, ref: PageRef) -> str:
        if ref.source_id not in self.registry:
            return ""
        src = self.registry.get(ref.source_id)
        return self.tr("{0} — page {1} of {2}").format(src.name, ref.page_index + 1, src.page_count)

    def _selected_rows(self) -> list[int]:
        return sorted(i.row() for i in self.view.selectionModel().selectedIndexes())

    def _apply_pages(self, pages: Sequence[PageRef], select: Sequence[int]) -> None:
        self.model.set_pages(pages)
        sm = self.view.selectionModel()
        sm.clearSelection()
        for r in select:
            if 0 <= r < self.model.rowCount():
                sm.select(self.model.index(r), QItemSelectionModel.SelectionFlag.Select)
        if select:
            first = min(select)
            if 0 <= first < self.model.rowCount():
                sm.setCurrentIndex(self.model.index(first), QItemSelectionModel.SelectionFlag.NoUpdate)
                self.view.scrollTo(self.model.index(first))
        self._refresh_sources_list()

    def _push(self, text: str, after: Sequence[PageRef], select_after: Sequence[int],
              on_redo=None, on_undo=None) -> None:
        self.undo.push(PagesCommand(text, self._apply_pages, self.model.pages, after,
                                    self._selected_rows(), select_after, on_redo, on_undo))

    def _refresh_sources_list(self) -> None:
        current = self.sources_list.currentItem()
        current_id = current.data(Qt.ItemDataRole.UserRole) if current else None
        self.sources_list.clear()
        used: dict[int, int] = {}
        for p in self.model.pages:
            used[p.source_id] = used.get(p.source_id, 0) + 1
        for src in self.registry:
            pm = QPixmap(14, 14)
            pm.fill(self._color_for(src.id))
            text = self.tr("{0}\n{1} of {2} pages used").format(src.name, used.get(src.id, 0), src.page_count)
            item = QListWidgetItem(QIcon(pm), text)
            item.setToolTip(safe_text.tooltip(src.path))
            item.setData(Qt.ItemDataRole.UserRole, src.id)
            self.sources_list.addItem(item)
            if src.id == current_id:
                self.sources_list.setCurrentItem(item)

    def _update_actions(self, *args) -> None:
        n = self.model.rowCount()
        sel = len(self._selected_rows()) if self.view.selectionModel() else 0
        for a in (self.act_delete, self.act_dup, self.act_rot_l, self.act_rot_r, self.act_up,
                  self.act_down, self.act_first, self.act_last, self.act_export_sel):
            a.setEnabled(sel > 0)
        self.act_reverse.setEnabled(sel > 1)
        self.act_export.setEnabled(n > 0)
        self.act_clear.setEnabled(len(self.registry) > 0)
        has_src = self.sources_list.currentItem() is not None if hasattr(self, "sources_list") else False
        if hasattr(self, "btn_remove"):
            self.btn_remove.setEnabled(has_src)
            self.btn_select_src.setEnabled(has_src)
        if hasattr(self, "lbl_count"):
            self.lbl_count.setText(self.tr("{0} pages · {1} selected").format(n, sel))
        title = APP_NAME
        if self.metadata.get("title"):
            title = f"{self.metadata['title']} — {APP_NAME}"
        self.setWindowTitle(title)

    def _zoom_changed(self, size: int) -> None:
        if self.zoom.value() != size:
            self.zoom.blockSignals(True)
            self.zoom.setValue(size)
            self.zoom.blockSignals(False)

    # ------------------------------------------------------------------ files
    def open_dialog(self) -> None:
        s = settings()
        paths, _ = QFileDialog.getOpenFileNames(
            self, self.tr("Open PDF files"), str(s.value("last_open_dir", os.path.expanduser("~"))),
            self.tr("PDF files (*.pdf);;All files (*)"))
        if paths:
            s.setValue("last_open_dir", os.path.dirname(paths[0]))
            self.open_files(paths)

    def _open_one(self, path: str) -> Optional[DocInfo]:
        password: Optional[str] = None
        retry = False
        while True:
            try:
                return self.registry.add(path, password)
            except PasswordRequired:
                password = PasswordDialog.ask(self, path, retry)
                retry = True
                if password is None:
                    return None

    def open_files(self, paths: Sequence[str], dest_row: Optional[int] = None) -> None:
        errors: list[str] = []
        added: list[DocInfo] = []
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            for path in paths:
                if not os.path.isfile(path):
                    errors.append(self.tr("{0}: file not found").format(path))
                    continue
                try:
                    src = self._open_one(path)
                except UnsafePdf as exc:
                    errors.append(self.tr("{0}: refused for safety reasons: {1}").format(os.path.basename(path), exc))
                    continue
                except WorkerCrashed:
                    errors.append(self.tr("{0}: the file could not be processed safely "
                                          "(the PDF reader stopped). It may be damaged or "
                                          "malicious.").format(os.path.basename(path)))
                    continue
                except NotAPdf as exc:
                    errors.append(self.tr("{0}: not a valid PDF ({1})").format(os.path.basename(path), exc))
                    continue
                except Exception as exc:
                    errors.append(f"{os.path.basename(path)}: {exc}")
                    continue
                if src is not None:
                    added.append(src)
        finally:
            self.unsetCursor()
        if added:
            new_refs = [PageRef(s.id, i) for s in added for i in range(s.page_count)]
            pages = self.model.pages
            at = len(pages) if dest_row is None else max(0, min(dest_row, len(pages)))
            after = pages[:at] + new_refs + pages[at:]
            if not self._metadata_edited and len(self.registry) == len(added):
                self._prefill_metadata(added[0])
            def redo(srcs=tuple(added)):
                for s in srcs:
                    self.registry.restore(s)

            def undo(srcs=tuple(added)):
                for s in srcs:
                    if s.id in self.registry:
                        self.registry.remove(s.id)
                        self.thumbs.forget_source(s.id)

            text = (self.tr("Open {0}").format(added[0].name) if len(added) == 1
                    else self.tr("Open {0} files").format(len(added)))
            self._push(text, after, [], redo, undo)
            self.view.scrollTo(self.model.index(at))
            self.statusBar().showMessage(self.tr("Added %n page(s)", "", len(new_refs)), 4000)
        if errors:
            safe_text.warning(self, self.tr("Some files could not be opened"), "\n".join(errors))

    def _prefill_metadata(self, src: DocInfo) -> None:
        meta = src.metadata
        # Only the title is taken over: author, keywords etc. of one input should not
        # silently leak into the merged document.
        self.metadata["title"] = (meta.get("title") or "").strip() or os.path.splitext(src.name)[0]

    def remove_current_source(self) -> None:
        item = self.sources_list.currentItem()
        if item is None:
            return
        sid = item.data(Qt.ItemDataRole.UserRole)
        src = self.registry.get(sid)
        after = [p for p in self.model.pages if p.source_id != sid]
        self._push(self.tr("Remove {0}").format(src.name), after, [],
                   on_redo=lambda: (self.registry.remove(sid), self.thumbs.forget_source(sid))
                   if sid in self.registry else None,
                   on_undo=lambda: self.registry.restore(src))

    def close_all(self) -> None:
        if not len(self.registry):
            return
        srcs = list(self.registry)
        self._push(self.tr("Close all files"), [], [],
                   on_redo=lambda: [self.registry.remove(s.id) for s in srcs if s.id in self.registry],
                   on_undo=lambda: [self.registry.restore(s) for s in srcs])

    def _select_source_pages(self, item) -> None:
        if item is None:
            return
        sid = item.data(Qt.ItemDataRole.UserRole)
        rows = [i for i, p in enumerate(self.model.pages) if p.source_id == sid]
        sm = self.view.selectionModel()
        sm.clearSelection()
        for r in rows:
            sm.select(self.model.index(r), QItemSelectionModel.SelectionFlag.Select)
        if rows:
            self.view.scrollTo(self.model.index(rows[0]))
        self.view.setFocus()

    # ------------------------------------------------------------------ editing
    def delete_selected(self) -> None:
        rows = set(self._selected_rows())
        if not rows:
            return
        pages = self.model.pages
        after = [p for i, p in enumerate(pages) if i not in rows]
        nxt = min(min(rows), len(after) - 1)
        self._push(self.tr("Delete %n page(s)", "", len(rows)), after, [nxt] if nxt >= 0 else [])

    def duplicate_selected(self) -> None:
        rows = set(self._selected_rows())
        if not rows:
            return
        after: list[PageRef] = []
        select: list[int] = []
        for i, p in enumerate(self.model.pages):
            after.append(p)
            if i in rows:
                after.append(p)
                select.append(len(after) - 1)
        self._push(self.tr("Duplicate %n page(s)", "", len(rows)), after, select)

    def rotate_selected(self, degrees: int) -> None:
        rows = self._selected_rows()
        if not rows:
            return
        after = self.model.pages
        for r in rows:
            after[r] = after[r].rotated(degrees)
        self._push(self.tr("Rotate %n page(s)", "", len(rows)), after, rows)

    def _move_rows(self, rows: Sequence[int], dest: int) -> None:
        pages = self.model.pages
        after, new_rows = move_rows(pages, rows, dest)
        if after != pages:
            self._push(self.tr("Move %n page(s)", "", len(new_rows)), after, new_rows)

    def move_selected(self, delta: int) -> None:
        rows = self._selected_rows()
        if not rows:
            return
        dest = rows[0] - 1 if delta < 0 else rows[-1] + 2
        self._move_rows(rows, max(0, dest))

    def move_selected_to(self, dest: Optional[int]) -> None:
        rows = self._selected_rows()
        if rows:
            self._move_rows(rows, self.model.rowCount() if dest is None else dest)

    def reverse_selected(self) -> None:
        rows = self._selected_rows()
        if len(rows) < 2:
            return
        after = self.model.pages
        vals = [after[r] for r in rows][::-1]
        for r, v in zip(rows, vals):
            after[r] = v
        self._push(self.tr("Reverse %n page(s)", "", len(rows)), after, rows)

    # ------------------------------------------------------------------ properties / export
    def edit_properties(self) -> None:
        dlg = PropertiesDialog(self.metadata, self)
        if dlg.exec():
            self.metadata = dlg.metadata()
            self._metadata_edited = True
            self._update_actions()

    def _load_export_options(self) -> ExportOptions:
        s = settings()
        s.beginGroup("export")
        d = {k: s.value(k) for k in s.childKeys()}
        s.endGroup()
        return ExportOptions.from_dict(d)

    def _save_export_options(self, opts: ExportOptions) -> None:
        s = settings()
        s.beginGroup("export")
        for k, v in opts.to_dict().items():
            s.setValue(k, v)
        s.endGroup()

    def export_dialog(self, selection_only: bool) -> None:
        pages = self.model.pages
        if not pages:
            return
        sel = self._selected_rows()
        dlg = ExportDialog(self._load_export_options(), len(pages), len(sel), selection_only, self)
        if not dlg.exec():
            return
        opts = dlg.options()
        self._save_export_options(opts)
        if dlg.selection_only():
            pages = [pages[r] for r in sel]
        s = settings()
        base = self.metadata.get("title") or self.tr("merged")
        base = "".join(c for c in base if c not in '<>:"/\\|?*').strip() or "merged"
        start = os.path.join(str(s.value("last_save_dir", os.path.expanduser("~"))), base + ".pdf")
        path, _ = QFileDialog.getSaveFileName(self, self.tr("Save PDF as"), start,
                                              self.tr("PDF files (*.pdf)"))
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        if any(same_file(path, src.path) for src in self.registry):
            safe_text.warning(self, self.tr("Export PDF"),
                                self.tr("The output file is one of the open input files. "
                                        "Please choose a different name."))
            return
        s.setValue("last_save_dir", os.path.dirname(path))
        self._run_export(pages, opts, path)

    def _run_export(self, pages, opts: ExportOptions, path: str) -> None:
        prog = QProgressDialog(self.tr("Exporting…"), self.tr("Cancel"), 0, len(pages) + 2, self)
        prog.setWindowTitle(self.tr("Export PDF"))
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        prog.setMinimumDuration(300)
        prog.setAutoClose(False)
        prog.setAutoReset(False)
        docs = [self.registry.get(sid) for sid in sorted({p.source_id for p in pages})]
        worker = ExportWorker(pages, docs, self.metadata, opts, path, self)
        self._export_worker = worker
        stage_text = {"pages": self.tr("Copying pages…"),
                      "images": self.tr("Optimizing images…"),
                      "saving": self.tr("Saving file…")}

        def on_progress(done, total, stage):
            prog.setLabelText(stage_text.get(stage, ""))
            prog.setValue(done + {"pages": 0, "images": 1, "saving": 2}.get(stage, 0))

        def finish():
            prog.close()
            self._export_worker = None
            worker.deleteLater()

        def ok(size):
            finish()
            self.statusBar().showMessage(self.tr("Saved {0} ({1})").format(path, human_size(size)), 8000)
            box = safe_text.message(self, QMessageBox.Icon.Information, self.tr("Export PDF"),
                                    self.tr("The PDF was saved successfully.\n\n{0}\n{1} pages, {2}")
                                    .format(path, len(pages), human_size(size)))
            open_btn = box.addButton(self.tr("Open file"), QMessageBox.ButtonRole.ActionRole)
            folder_btn = box.addButton(self.tr("Open folder"), QMessageBox.ButtonRole.ActionRole)
            box.addButton(QMessageBox.StandardButton.Close)
            box.exec()
            if box.clickedButton() is open_btn:
                QDesktopServices.openUrl(QUrl.fromLocalFile(path))
            elif box.clickedButton() is folder_btn:
                QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))

        def failed(msg):
            finish()
            safe_text.critical(self, self.tr("Export PDF"), self.tr("Export failed:\n{0}").format(msg))

        def cancelled():
            finish()
            self.statusBar().showMessage(self.tr("Export cancelled"), 4000)

        worker.progress.connect(on_progress)
        worker.finished_ok.connect(ok)
        worker.failed.connect(failed)
        worker.cancelled.connect(cancelled)
        prog.canceled.connect(worker.cancel)
        worker.start()

    # ------------------------------------------------------------------ misc
    def about(self) -> None:
        import html
        from PySide6 import __version__ as pyside_version
        try:
            info = self.client.hello()
            pymupdf_version = html.escape(str(info.get("pymupdf", "?"))[:20])
            level = self.client.sandbox_level
        except Exception:
            pymupdf_version, level = "?", "unavailable"
        levels = {"low-integrity": self.tr("low-integrity process with resource limits"),
                  "job-only": self.tr("separate process with resource limits"),
                  "rlimit-only": self.tr("separate process with memory limit"),
                  "unsandboxed": self.tr("separate process, not sandboxed (running from source)")}
        QMessageBox.about(
            self, self.tr("About {0}").format(APP_NAME),
            self.tr("<h3>{0} {1}</h3><p>Merge, reorder, rotate and compress PDF files.</p>"
                    "<p>Free software under the GNU Affero General Public License v3.</p>"
                    "<p>Built with PyMuPDF {2} and Qt for Python {3}.</p>")
            .format(APP_NAME, __version__, pymupdf_version, pyside_version)
            + "<p>" + self.tr("PDF files are processed in a sandbox: {0}.")
            .format(html.escape(levels.get(level, level))) + "</p>")

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls()
                 if u.isLocalFile() and u.toLocalFile().lower().endswith(".pdf")]
        if paths:
            e.acceptProposedAction()
            QTimer.singleShot(0, lambda: self.open_files(paths))

    def _restore_settings(self) -> None:
        s = settings()
        geo = s.value("window/geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        else:
            self.resize(1100, 720)
        state = s.value("window/state")
        if state is not None:
            self.restoreState(state)
        try:
            self.view.set_thumb_size(int(s.value("thumb_size", 160)))
        except (TypeError, ValueError):
            pass

    def closeEvent(self, e):
        if self._export_worker is not None:
            QMessageBox.information(self, APP_NAME, self.tr("Please wait until the export finishes."))
            e.ignore()
            return
        s = settings()
        s.setValue("window/geometry", self.saveGeometry())
        s.setValue("window/state", self.saveState())
        s.setValue("thumb_size", self.view.thumb_size)
        s.sync()
        self.thumbs.shutdown()
        self.client.shutdown()
        super().closeEvent(e)
