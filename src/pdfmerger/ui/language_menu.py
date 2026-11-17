from __future__ import annotations

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QMenu, QMessageBox

from ..core.settings import settings
from ..i18n import LANGUAGES, system_language


def tr(text: str) -> str:
    return QCoreApplication.translate("LanguageMenu", text)


def build_language_menu(window) -> QMenu:
    menu = QMenu(tr("&Language"), window)
    group = QActionGroup(menu)
    group.setExclusive(True)
    current = str(settings().value("language", "system"))
    system_name = LANGUAGES[system_language()]
    entries = [("system", tr("System default ({0})").format(system_name))]
    entries += list(LANGUAGES.items())
    for code, label in entries:
        act = QAction(label, menu, checkable=True)
        act.setData(code)
        act.setChecked(code == current or (code == "system" and current not in LANGUAGES))
        group.addAction(act)
        menu.addAction(act)
        if code == "system":
            menu.addSeparator()

    def changed(act: QAction) -> None:
        settings().setValue("language", act.data())
        settings().sync()
        QMessageBox.information(window, tr("Language"),
                                tr("The new language will be used the next time you start the application."))

    group.triggered.connect(changed)
    return menu
