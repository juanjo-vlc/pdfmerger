import pytest
from PySide6.QtCore import QSettings, QMimeData, QByteArray, QModelIndex, Qt

from pdfmerger.core import settings as settings_mod
from pdfmerger.core.pages import PageRef
from pdfmerger.ui.page_model import ROW_MIME, PageModel, move_rows

from conftest import page_labels


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path):
    settings_mod.set_settings(QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    yield
    settings_mod.set_settings(None)


@pytest.fixture
def win(qtbot):
    from pdfmerger.ui.main_window import MainWindow
    w = MainWindow()
    qtbot.addWidget(w)
    w.show()
    yield w
    w.close()


def labels(win):
    return [f"{win.registry.get(p.source_id).name[0].upper()}{p.page_index + 1}" for p in win.model.pages]


def select(win, rows):
    from PySide6.QtCore import QItemSelectionModel
    sm = win.view.selectionModel()
    sm.clearSelection()
    for r in rows:
        sm.select(win.model.index(r), QItemSelectionModel.SelectionFlag.Select)


@pytest.mark.parametrize("rows,dest,expected,new", [
    ([0], 3, [1, 2, 0, 3], [2]),
    ([3], 0, [3, 0, 1, 2], [0]),
    ([0, 2], 4, [1, 3, 0, 2], [2, 3]),
    ([1, 2], 1, [0, 1, 2, 3], [1, 2]),
    ([2, 0], 10, [1, 3, 0, 2], [2, 3]),
])
def test_move_rows(rows, dest, expected, new):
    pages = [PageRef(1, i) for i in range(4)]
    out, sel = move_rows(pages, rows, dest)
    assert [p.page_index for p in out] == expected
    assert sel == new


def test_open_edit_undo(win, pdf_a, pdf_b):
    win.open_files([pdf_a, pdf_b])
    assert labels(win) == ["A1", "A2", "A3", "B1", "B2"]
    assert win.metadata["title"] == "a"
    assert win.sources_list.count() == 2

    select(win, [1])
    win.delete_selected()
    assert labels(win) == ["A1", "A3", "B1", "B2"]

    select(win, [0])
    win.duplicate_selected()
    assert labels(win) == ["A1", "A1", "A3", "B1", "B2"]
    assert win._selected_rows() == [1]

    select(win, [3, 4])
    win.move_selected_to(0)
    assert labels(win) == ["B1", "B2", "A1", "A1", "A3"]

    select(win, [0])
    win.rotate_selected(90)
    assert win.model.page(0).rotation == 90
    win.rotate_selected(270)
    assert win.model.page(0).rotation == 0

    select(win, [0, 1])
    win.reverse_selected()
    assert labels(win) == ["B2", "B1", "A1", "A1", "A3"]

    for _ in range(6):
        win.undo.undo()
    assert labels(win) == ["A1", "A2", "A3", "B1", "B2"]
    win.undo.undo()  # undo open
    assert win.model.rowCount() == 0 and len(win.registry) == 0
    win.undo.redo()
    assert len(win.registry) == 2 and win.model.rowCount() == 5


def test_remove_source_and_undo(win, pdf_a, pdf_b):
    win.open_files([pdf_a, pdf_b])
    win.sources_list.setCurrentRow(0)
    win.remove_current_source()
    assert labels(win) == ["B1", "B2"]
    assert len(win.registry) == 1
    win.undo.undo()
    assert labels(win) == ["A1", "A2", "A3", "B1", "B2"]
    assert len(win.registry) == 2


def test_drop_rows_moves_via_undo(win, pdf_a):
    win.open_files([pdf_a])
    md = QMimeData()
    md.setData(ROW_MIME, QByteArray(b"[0]"))
    assert win.model.dropMimeData(md, Qt.DropAction.MoveAction, 3, 0, QModelIndex()) is False
    assert labels(win) == ["A2", "A3", "A1"]
    win.undo.undo()
    assert labels(win) == ["A1", "A2", "A3"]


def test_password_prompt(win, pdf_locked, monkeypatch):
    from pdfmerger.ui import main_window
    answers = iter(["bad", "secret"])
    monkeypatch.setattr(main_window.PasswordDialog, "ask", staticmethod(lambda *a: next(answers)))
    win.open_files([pdf_locked])
    assert labels(win) == ["L1"]


def test_thumbnails_render(win, pdf_a, qtbot):
    win.open_files([pdf_a])
    with qtbot.waitSignal(win.thumbs.ready, timeout=5000):
        win.thumbs.get(win.model.page(0).source_id, 0, 128)
    assert win.thumbs.get(win.model.page(0).source_id, 0, 128) is not None


def test_export_worker(win, pdf_a, pdf_b, tmp_path, qtbot):
    from pdfmerger.core.quality import ExportOptions
    from pdfmerger.ui.main_window import ExportWorker
    win.open_files([pdf_a, pdf_b])
    select(win, [4])
    win.move_selected_to(0)
    out = tmp_path / "out.pdf"
    w = ExportWorker(win.model.pages, win.registry, {"title": "T"}, ExportOptions(), str(out))
    with qtbot.waitSignal(w.finished_ok, timeout=10000):
        w.start()
    w.wait()
    assert page_labels(out) == ["B2", "A1", "A2", "A3", "B1"]


def test_export_dialog_presets(qtbot):
    from pdfmerger.core.quality import ExportOptions
    from pdfmerger.ui.export_dialog import ExportDialog
    dlg = ExportDialog(ExportOptions(), 5, 2)
    qtbot.addWidget(dlg)
    assert dlg.preset.currentData() == "original"
    dlg.preset.setCurrentIndex(dlg.preset.findData("screen"))
    o = dlg.options()
    assert o.downsample and o.dpi_target == 72 and o.jpeg_quality == 60
    dlg.sl_q.setValue(33)
    assert dlg.preset.currentData() == "custom"
    dlg.g_s.setChecked(True)
    dlg.ed_user.setText("pw")
    assert dlg.options().encryption.user_password == "pw"


def test_properties_dialog(qtbot):
    from pdfmerger.ui.properties_dialog import PropertiesDialog
    dlg = PropertiesDialog({"title": "X", "creationDate": "D:20240102030405+00'00'"})
    qtbot.addWidget(dlg)
    dlg.edits["author"].setText("Ana")
    m = dlg.metadata()
    assert m["title"] == "X" and m["author"] == "Ana"
    assert m["creationDate"].startswith("D:20240102030405")
    assert m["modDate"] == ""


def test_language_resolution():
    from pdfmerger.i18n import resolve_language
    assert resolve_language("es") == "es"
    assert resolve_language("system") in ("en", "es", "fr")
    assert resolve_language("xx") in ("en", "es", "fr")


@pytest.mark.parametrize("payload", [b"not json", b'{"a": 1}', b"[999]", b'["0"]', b"[]", b"[true]"])
def test_drop_rejects_malformed_rows(win, pdf_a, payload):
    win.open_files([pdf_a])
    md = QMimeData()
    md.setData(ROW_MIME, QByteArray(payload))
    win.model.dropMimeData(md, Qt.DropAction.MoveAction, 0, 0, QModelIndex())
    assert labels(win) == ["A1", "A2", "A3"]
    assert win.undo.count() == 1   # only the "open" command


def test_tooltips_escape_markup(win, pdf_a, monkeypatch):
    # "<" and ">" are not allowed in Windows file names, so inject the markup via the label
    win.open_files([pdf_a])
    monkeypatch.setattr(win.model, "_label_for", lambda ref: "<b>x</b> & <img src=y>")
    tip = win.model.data(win.model.index(0), Qt.ItemDataRole.ToolTipRole)
    assert "<b>" not in tip and "<img" not in tip
    assert "&lt;b&gt;" in tip and "&amp;" in tip


def test_prefill_only_title(win, tmp_path):
    import pymupdf
    path = tmp_path / "meta.pdf"
    d = pymupdf.open(); d.new_page()
    d.set_metadata({"title": "T", "author": "Someone", "keywords": "internal"})
    d.save(str(path)); d.close()
    win.open_files([str(path)])
    assert win.metadata.get("title") == "T"
    assert not win.metadata.get("author") and not win.metadata.get("keywords")
