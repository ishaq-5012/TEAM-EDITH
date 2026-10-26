"""Synthetic test documents, generated in memory. Contains no real personal or customer data."""

from __future__ import annotations

import io

import pymupdf
from PIL import Image

LABEL = "SYNTHETIC TEST DOCUMENT - NOT A REAL RECORD"


def pdf(
    pages: int = 1, *, text: bool = True, javascript: bool = False, encrypted: bool = False, embedded: bool = False,
    marker: str = "",
) -> bytes:
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page(width=595, height=842)
        if text:
            page.insert_text((72, 72), f"{LABEL} page {i + 1} {marker}", fontsize=11)
        else:
            # Raster-only page: draw shapes, no text layer.
            page.draw_rect(pymupdf.Rect(72, 72, 300, 200), color=(0, 0, 0), fill=(0.8, 0.8, 0.8))
    if javascript:
        doc.set_pagelayout("SinglePage")
        xref = doc.get_new_xref()
        doc.update_object(xref, "<< /Type /Action /S /JavaScript /JS (app.alert('synthetic');) >>")
        catalog = doc.pdf_catalog()
        doc.xref_set_key(catalog, "OpenAction", f"{xref} 0 R")
    if embedded:
        doc.embfile_add("synthetic.txt", b"synthetic embedded payload")
    buf = io.BytesIO()
    if encrypted:
        doc.save(buf, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="synthetic-user", owner_pw="synthetic-owner")
    else:
        doc.save(buf)
    doc.close()
    return buf.getvalue()


def png(width: int = 120, height: int = 80, color: tuple[int, int, int] = (40, 60, 160)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, format="PNG")
    return buf.getvalue()


def jpeg(width: int = 120, height: int = 80) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (200, 120, 40)).save(buf, format="JPEG")
    return buf.getvalue()


def labelled_pdf(pages: list[list[str]], *, rotation: int = 0, scanned: bool = False, fontsize: float = 11) -> bytes:
    """Synthetic "Label: value" PDF. One list of lines per page, written from (72, 100) downwards, 18pt apart.

    scanned=True renders each page to an image and embeds only the image: no text layer, like a real scan.
    """
    src = pymupdf.open()
    for lines in pages:
        page = src.new_page(width=595, height=842)
        page.insert_text((72, 60), LABEL, fontsize=9)
        for i, line in enumerate(lines):
            page.insert_text((72, 100 + i * 18), line, fontsize=fontsize)
    if scanned:
        out = pymupdf.open()
        for page in src:
            pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2))
            target = out.new_page(width=595, height=842)
            target.insert_image(target.rect, stream=pix.tobytes("png"))
        src.close()
        src = out
    if rotation:
        for page in src:
            page.set_rotation(rotation)
    buf = io.BytesIO()
    src.save(buf)
    src.close()
    return buf.getvalue()
