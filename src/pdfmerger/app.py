"""Application entry point.

Dispatches before importing Qt: the PDF worker (``--worker``) never loads Qt, keeping
the sandboxed process small and free of GUI code.
"""
from __future__ import annotations

import os
import sys

from . import APP_NAME, __version__

ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "icons")


def _set_windows_app_id() -> None:
    """Give the taskbar our own icon instead of python's."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"PDFMerger.{__version__}")
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    if "--worker" in argv[1:]:
        from .core.worker import main as worker_main
        return worker_main(argv)
    from .cli import run, wants_cli
    if wants_cli(argv):
        return run(argv)
    return gui_main(argv)


def gui_main(argv: list[str]) -> int:
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from .core.settings import settings
    from .i18n import install_translators, resolve_language

    _set_windows_app_id()
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName("PDFMerger")
    icon_path = os.path.join(ICON_DIR, "app.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    install_translators(app, resolve_language(str(settings().value("language", "system"))))

    from .ui.main_window import MainWindow  # import after translators are installed
    win = MainWindow()
    win.show()
    files = [a for a in argv[1:] if a.lower().endswith(".pdf")]
    if files:
        QTimer.singleShot(0, lambda: win.open_files(files))
    return app.exec()
