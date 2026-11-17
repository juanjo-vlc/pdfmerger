"""Show untrusted text (file names, parser messages) without rich-text interpretation.

Qt auto-detects HTML in labels, message boxes and tooltips, so a file named
``<img src=...>.pdf`` would otherwise be rendered as markup.
"""
from __future__ import annotations

import html

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QWidget


def tooltip(text: str) -> str:
    """Tooltips can't be forced to plain text, so escape and mark as rich text explicitly."""
    return "<qt>" + html.escape(text).replace("\n", "<br>") + "</qt>"


def message(parent: QWidget, icon: QMessageBox.Icon, title: str, text: str) -> QMessageBox:
    box = QMessageBox(icon, title, text, parent=parent)
    box.setTextFormat(Qt.TextFormat.PlainText)
    return box


def warning(parent: QWidget, title: str, text: str) -> None:
    box = message(parent, QMessageBox.Icon.Warning, title, text)
    box.addButton(QMessageBox.StandardButton.Ok)
    box.exec()


def critical(parent: QWidget, title: str, text: str) -> None:
    box = message(parent, QMessageBox.Icon.Critical, title, text)
    box.addButton(QMessageBox.StandardButton.Ok)
    box.exec()
