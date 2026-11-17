"""Edit the output document's metadata."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QDateTime
from PySide6.QtWidgets import (QCheckBox, QDateTimeEdit, QDialog, QDialogButtonBox,
                               QFormLayout, QHBoxLayout, QLineEdit, QPlainTextEdit,
                               QVBoxLayout, QWidget)

from ..core.pdfdates import parse_pdf_date, pdf_date


class PropertiesDialog(QDialog):
    TEXT_FIELDS = ("title", "author", "subject", "creator", "producer")

    def __init__(self, metadata: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Document properties"))
        self.setMinimumWidth(460)
        form = QFormLayout()
        labels = {
            "title": self.tr("Title:"),
            "author": self.tr("Author:"),
            "subject": self.tr("Subject:"),
            "creator": self.tr("Creator (application):"),
            "producer": self.tr("Producer:"),
        }
        self.edits: dict[str, QLineEdit] = {}
        for key in self.TEXT_FIELDS:
            e = QLineEdit(metadata.get(key, "") or "")
            self.edits[key] = e
            form.addRow(labels[key], e)
            if key == "subject":
                self.keywords = QPlainTextEdit(metadata.get("keywords", "") or "")
                self.keywords.setPlaceholderText(self.tr("Comma-separated keywords"))
                self.keywords.setFixedHeight(60)
                form.addRow(self.tr("Keywords:"), self.keywords)

        self.created = self._date_row(form, self.tr("Created:"), metadata.get("creationDate", ""))
        self.modified = self._date_row(form, self.tr("Modified:"), metadata.get("modDate", ""),
                                       now_label=self.tr("Use export time"))
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _date_row(self, form: QFormLayout, label: str, value: str, now_label: str = ""):
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        auto = QCheckBox(now_label or self.tr("Use export time"))
        edit = QDateTimeEdit()
        edit.setCalendarPopup(True)
        edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        dt = parse_pdf_date(value)
        auto.setChecked(dt is None)
        edit.setDateTime(QDateTime(dt) if dt else QDateTime.currentDateTime())
        edit.setEnabled(dt is not None)
        auto.toggled.connect(lambda on: edit.setEnabled(not on))
        h.addWidget(edit, 1)
        h.addWidget(auto)
        form.addRow(label, row)
        return auto, edit

    @staticmethod
    def _date_value(pair) -> str:
        auto, edit = pair
        if auto.isChecked():
            return ""
        return pdf_date(edit.dateTime().toPython())

    def metadata(self) -> dict:
        m = {k: e.text().strip() for k, e in self.edits.items()}
        m["keywords"] = self.keywords.toPlainText().strip()
        m["creationDate"] = self._date_value(self.created)
        m["modDate"] = self._date_value(self.modified)
        return m
