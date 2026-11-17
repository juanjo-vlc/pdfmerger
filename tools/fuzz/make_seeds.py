"""Write a small seed corpus of uncompressed PDFs exercising many features.

Uncompressed streams (expand=255) give the mutator readable structure to work with.
Usage: python make_seeds.py OUTDIR
"""
import os
import sys

import pymupdf


def save(doc, path):
    doc.save(path, garbage=1, expand=255)
    doc.close()


def main(out: str) -> None:
    os.makedirs(out, exist_ok=True)
    # 1. plain text, several pages, rotation
    d = pymupdf.open()
    for i in range(3):
        p = d.new_page()
        p.insert_text((72, 72), f"Page {i}", fontsize=20)
        p.set_rotation(90 * i)
    save(d, f"{out}/text.pdf")
    # 2. images (RGB, gray) and vector drawing
    d = pymupdf.open()
    p = d.new_page()
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 32, 32), False)
    pix.clear_with(128)
    p.insert_image(pymupdf.Rect(50, 50, 250, 250), pixmap=pix)
    gray = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 16, 16), False)
    gray.clear_with(200)
    p.insert_image(pymupdf.Rect(300, 50, 400, 150), pixmap=gray)
    p.draw_rect(pymupdf.Rect(60, 300, 300, 400), color=(1, 0, 0), fill=(0, 0, 1))
    save(d, f"{out}/images.pdf")
    # 3. active content: link, form field with JS, page-open JS, attachment
    d = pymupdf.open()
    p = d.new_page()
    p.insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(72, 80, 200, 100),
                   "uri": "https://example.invalid/"})
    w = pymupdf.Widget()
    w.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
    w.field_name = "f"
    w.rect = pymupdf.Rect(72, 120, 250, 140)
    w.script = "app.alert(1)"
    p.add_widget(w)
    js = d.get_new_xref()
    d.update_object(js, "<< /S /JavaScript /JS (app.alert(2)) >>")
    d.xref_set_key(p.xref, "AA", f"<< /O {js} 0 R >>")
    d.embfile_add("a.txt", b"hello")
    p.add_text_annot((300, 300), "note")
    save(d, f"{out}/active.pdf")
    # 4. outlines / internal links / fonts
    d = pymupdf.open()
    for i in range(2):
        d.new_page().insert_text((72, 72), "Ünïcødé ✓", fontname="helv")
    d.set_toc([[1, "One", 1], [2, "Two", 2]])
    d[0].insert_link({"kind": pymupdf.LINK_GOTO, "from": pymupdf.Rect(0, 0, 50, 50), "page": 1})
    save(d, f"{out}/outline.pdf")
    # 5. empty-ish and odd page sizes
    d = pymupdf.open()
    d.new_page(width=10, height=4000)
    d.new_page(width=3000, height=3000)
    save(d, f"{out}/sizes.pdf")
    print(f"seeds written to {out}: {sorted(os.listdir(out))}")


if __name__ == "__main__":
    main(sys.argv[1])
