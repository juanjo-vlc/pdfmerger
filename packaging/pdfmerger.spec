# -*- mode: python ; coding: utf-8 -*-
# Build:  pyinstaller --noconfirm --clean packaging/pdfmerger.spec
# Produces a portable folder: dist/PDFMerger/PDFMerger.exe
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
SRC = os.path.join(ROOT, "src")
PKG = os.path.join(SRC, "pdfmerger")

with open(os.path.join(PKG, "__init__.py"), encoding="utf-8") as fh:
    VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', fh.read()).group(1)
vt = tuple(int(x) for x in (VERSION.split(".") + ["0"] * 4)[:4])

qm_files = [f for f in os.listdir(os.path.join(PKG, "i18n")) if f.endswith(".qm")]
if not qm_files:
    sys.exit("No .qm translation files found - run pyside6-lrelease first (see build scripts).")

datas = [(os.path.join(PKG, "i18n", f), "pdfmerger/i18n") for f in qm_files]
datas += [(os.path.join(PKG, "resources", "icons", f), "pdfmerger/resources/icons")
          for f in os.listdir(os.path.join(PKG, "resources", "icons"))]
datas += [(os.path.join(ROOT, "LICENSE"), "."), (os.path.join(ROOT, "README.md"), ".")]

# Qt modules we never use: keep the portable folder small.
EXCLUDES = [
    "tkinter", "unittest", "pydoc_data", "numpy",
    "pymupdf.layout", "pymupdf4llm", "pymupdf_layout", "onnxruntime",
    # No network use at all: drop TLS/OpenSSL (hashlib falls back to built-in hashes)
    "ssl", "_ssl", "_hashlib",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel", "PySide6.QtWebSockets", "PySide6.QtQml", "PySide6.QtQuick",
    "PySide6.QtQuickWidgets", "PySide6.QtQuick3D", "PySide6.Qt3DCore", "PySide6.Qt3DRender",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtGraphs", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtBluetooth", "PySide6.QtPositioning",
    "PySide6.QtLocation", "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtNetwork",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtDesigner", "PySide6.QtHelp",
    "PySide6.QtSvgWidgets", "PySide6.QtXml", "PySide6.QtConcurrent", "PySide6.QtDBus",
]

version_info = None
if sys.platform == "win32":  # pefile (needed by versioninfo) only exists on Windows
    from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct,
                                                     StringTable, VarFileInfo, VarStruct,
                                                     VSVersionInfo)
    version_info = VSVersionInfo(
        ffi=FixedFileInfo(filevers=vt, prodvers=vt),
        kids=[
            StringFileInfo([StringTable("040904B0", [
                StringStruct("CompanyName", "PDF Merger contributors"),
                StringStruct("FileDescription", "PDF Merger"),
                StringStruct("FileVersion", VERSION),
                StringStruct("InternalName", "PDFMerger"),
                StringStruct("LegalCopyright", "AGPL-3.0-or-later"),
                StringStruct("OriginalFilename", "PDFMerger.exe"),
                StringStruct("ProductName", "PDF Merger"),
                StringStruct("ProductVersion", VERSION),
            ])]),
            VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
        ],
    )

a = Analysis(
    [os.path.join(SPECPATH, "launcher.py")],
    pathex=[SRC],
    datas=datas,
    hiddenimports=[],
    excludes=EXCLUDES,
    noarchive=False,
)


# Qt plugins/libraries the app does not need (smaller attack surface and download):
# the app renders pages itself and only loads PNG (built into QtGui).
DROP_QT = (
    "/plugins/imageformats/",          # gif, jpeg, tiff, webp, svg, ... decoders
    "/plugins/iconengines/",           # SVG icon engine
    "/plugins/generic/",               # TUIO touch (the reason Qt6Network was bundled)
    "/plugins/tls/", "/plugins/networkinformation/",
    "/plugins/platforms/qdirect2d", "/plugins/platforms/qminimal",
    "/plugins/platforms/qoffscreen",
    "opengl32sw.dll", "Qt6Network.dll", "Qt6Svg.dll",
    "libQt6Network.so", "libQt6Svg.so",
)
DROP_PY = ("libssl", "libcrypto", "_ssl.", "_hashlib.")


def _keep(entry):
    dest = entry[0].replace("\\", "/")
    base = dest.rsplit("/", 1)[-1]
    if dest.startswith("PySide6/") and any(d in "/" + dest for d in DROP_QT):
        return False
    if "/" not in dest and base.startswith(DROP_PY):
        return False
    # PyMuPDF extras we don't use: AI layout model and C/C++ development headers
    if dest.startswith(("pymupdf/layout/", "pymupdf/mupdf-devel/", "pymupdf4llm/",
                        "pymupdf_layout/")):
        return False
    # Qt's own translations: only the languages the app ships
    if dest.startswith("PySide6/") and "/translations/" in dest:
        name = dest.rsplit("/", 1)[-1]
        return name.startswith("qtbase_") and name[7:9] in LANGS
    return True


LANGS = {f[len("pdfmerger_"):len("pdfmerger_") + 2] for f in qm_files}
a.datas = [d for d in a.datas if _keep(d)]
a.binaries = [b for b in a.binaries if _keep(b)]

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PDFMerger",
    console=False,
    icon=os.path.join(PKG, "resources", "icons", "app.ico"),
    version=version_info,
    upx=False,   # UPX-packed binaries trigger antivirus false positives
)
coll = COLLECT(exe, a.binaries, a.datas, name="PDFMerger", upx=False)
