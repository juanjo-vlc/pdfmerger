from __future__ import annotations

import os
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QLineEdit, QVBoxLayout,
                               QWidget)


class PasswordDialog(QDialog):
    def __init__(self, path: str, retry: bool, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Password required"))
        lay = QVBoxLayout(self)
        msg = self.tr("The file \"{0}\" is protected. Enter its password:").format(os.path.basename(path))
        label = QLabel(msg)
        label.setTextFormat(Qt.TextFormat.PlainText)   # the file name is untrusted
        label.setWordWrap(True)
        lay.addWidget(label)
        if retry:
            err = QLabel(self.tr("Incorrect password, please try again."))
            err.setStyleSheet("color: #c0392b;")
            lay.addWidget(err)
        self.edit = QLineEdit()
        self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        lay.addWidget(self.edit)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    @staticmethod
    def ask(parent, path: str, retry: bool) -> Optional[str]:
        dlg = PasswordDialog(path, retry, parent)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            return dlg.edit.text()
        return None
