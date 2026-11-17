"""Translation loading. Compiled .qm files live next to this module."""
from __future__ import annotations

import os
from typing import Optional

from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
from PySide6.QtWidgets import QApplication

# code -> native name (shown untranslated so users can always find their language)
LANGUAGES = {"en": "English", "es": "Español", "fr": "Français"}
I18N_DIR = os.path.dirname(os.path.abspath(__file__))


def system_language() -> str:
    for tag in QLocale.system().uiLanguages():
        code = tag.replace("_", "-").split("-")[0].lower()
        if code in LANGUAGES:
            return code
    return "en"


def resolve_language(setting: Optional[str]) -> str:
    if setting and setting in LANGUAGES:
        return setting
    return system_language()


def install_translators(app: QApplication, lang: str) -> list[QTranslator]:
    """Install Qt's own and our translations. English also gets a translator
    so that plural forms ("%n page(s)") render correctly."""
    installed: list[QTranslator] = []
    qt_dir = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    candidates = [(f"pdfmerger_{lang}", I18N_DIR)]
    if lang != "en":
        candidates.insert(0, (f"qtbase_{lang}", qt_dir))
    for name, directory in candidates:
        tr = QTranslator(app)
        if tr.load(name, directory):
            app.installTranslator(tr)
            installed.append(tr)
    QLocale.setDefault(QLocale(lang))
    return installed
