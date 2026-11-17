import os

import pymupdf
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class ModalDialogOpened(AssertionError):
    pass


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    """A modal dialog nobody can click blocks the test run forever (offscreen in CI).
    Fail the test with the dialog's text instead; tests that expect a dialog patch it."""
    from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox

    def fail_exec(self, *a, **kw):
        text = self.text() if isinstance(self, QMessageBox) else ""
        raise ModalDialogOpened(f"modal {type(self).__name__} opened: "
                                f"{self.windowTitle()!r} {text!r}")

    def fail_static(name):
        def f(*a, **kw):
            raise ModalDialogOpened(f"QMessageBox/QFileDialog.{name} opened: {a[1:3]!r}")
        return staticmethod(f)

    for cls in (QDialog, QMessageBox, QFileDialog):
        monkeypatch.setattr(cls, "exec", fail_exec)
    for name in ("question", "warning", "information", "critical", "about"):
        monkeypatch.setattr(QMessageBox, name, fail_static(name))
    for name in ("getOpenFileName", "getOpenFileNames", "getSaveFileName", "getExistingDirectory"):
        monkeypatch.setattr(QFileDialog, name, fail_static(name))


def make_pdf(path, labels, image=False, password=None, rotate=0):
    doc = pymupdf.open()
    for label in labels:
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), label, fontsize=24)
        if rotate:
            page.set_rotation(rotate)
        if image:
            # a large noisy RGB image -> compresses badly, benefits from downsampling
            pix = pymupdf.Pixmap(pymupdf.csRGB, 1600, 1600, os.urandom(1600 * 1600 * 3), False)
            page.insert_image(pymupdf.Rect(72, 150, 523, 601), pixmap=pix)
    kw = {}
    if password:
        kw = dict(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=password, owner_pw=password)
    doc.save(str(path), **kw)
    doc.close()
    return str(path)


@pytest.fixture
def pdf_a(tmp_path):
    return make_pdf(tmp_path / "a.pdf", ["A1", "A2", "A3"])


@pytest.fixture
def pdf_b(tmp_path):
    return make_pdf(tmp_path / "b.pdf", ["B1", "B2"])


@pytest.fixture
def pdf_locked(tmp_path):
    return make_pdf(tmp_path / "locked.pdf", ["L1"], password="secret")


@pytest.fixture
def pdf_images(tmp_path):
    return make_pdf(tmp_path / "img.pdf", ["I1", "I2"], image=True)


def page_labels(path, password=None):
    doc = pymupdf.open(path)
    if password:
        assert doc.authenticate(password)
    labels = [p.get_text().strip() for p in doc]
    doc.close()
    return labels
