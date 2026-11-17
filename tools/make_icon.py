"""Generate the application icon (PNG + multi-size ICO) with Qt only.

Usage: python tools/make_icon.py
"""
import os
import struct
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPainterPath, QPen

OUT = os.path.join(os.path.dirname(__file__), "..", "src", "pdfmerger", "resources", "icons")


def draw(size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size / 256.0

    def page(x, y, color, fold=True):
        path = QPainterPath()
        w, h, f = 120 * s, 156 * s, 34 * s
        path.moveTo(x, y)
        path.lineTo(x + w - f, y)
        path.lineTo(x + w, y + f)
        path.lineTo(x + w, y + h)
        path.lineTo(x, y + h)
        path.closeSubpath()
        p.setPen(QPen(QColor(0, 0, 0, 60), max(1.0, 3 * s)))
        p.setBrush(color)
        p.drawPath(path)

    page(28 * s, 24 * s, QColor("#e67e22"))
    page(68 * s, 52 * s, QColor("#2e86de"))
    page(108 * s, 80 * s, QColor("#ffffff"))
    p.setPen(QColor("#c0392b"))
    f = QFont("Sans Serif")
    f.setBold(True)
    f.setPixelSize(int(44 * s))
    p.setFont(f)
    p.drawText(QRectF(108 * s, 120 * s, 120 * s, 70 * s), Qt.AlignmentFlag.AlignCenter, "PDF")
    p.end()
    return img


def png_bytes(img: QImage) -> bytes:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba)


def write_ico(path: str, sizes=(16, 24, 32, 48, 64, 128, 256)) -> None:
    images = [png_bytes(draw(sz)) for sz in sizes]
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries = b""
    for sz, data in zip(sizes, images):
        dim = 0 if sz >= 256 else sz
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    with open(path, "wb") as fh:
        fh.write(header + entries + b"".join(images))


if __name__ == "__main__":
    app = QGuiApplication(sys.argv)
    os.makedirs(OUT, exist_ok=True)
    draw(256).save(os.path.join(OUT, "app.png"))
    write_ico(os.path.join(OUT, "app.ico"))
    print("icons written to", os.path.abspath(OUT))
