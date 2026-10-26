"""Synthetic demo documents for manual testing.

Every file is generated, contains only invented placeholder text, and is labelled
SYNTHETIC on its face. Nothing here is real customer or personal data.
"""

from __future__ import annotations

import io
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw

BANNER = "SYNTHETIC DEMO DOCUMENT - NOT A REAL RECORD"


def _pdf(lines: list[str], pages: int = 1, text: bool = True, javascript: bool = False, rotation: int = 0) -> bytes:
    doc = pymupdf.open()
    for n in range(pages):
        page = doc.new_page(width=595, height=842)
        if text:
            page.insert_text((56, 60), BANNER, fontsize=12, color=(0.7, 0, 0))
            for i, line in enumerate(lines):
                page.insert_text((56, 100 + i * 18), line, fontsize=11)
            page.insert_text((56, 800), f"Page {n + 1} of {pages}", fontsize=9)
        else:
            page.draw_rect(pymupdf.Rect(56, 60, 539, 300), color=(0.2, 0.2, 0.2), fill=(0.9, 0.9, 0.9))
    if rotation:
        for page in doc:
            page.set_rotation(rotation)
    if javascript:
        xref = doc.get_new_xref()
        doc.update_object(xref, "<< /Type /Action /S /JavaScript /JS (app.alert('synthetic demo');) >>")
        doc.xref_set_key(doc.pdf_catalog(), "OpenAction", f"{xref} 0 R")
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


def _png() -> bytes:
    img = Image.new("RGB", (900, 560), (246, 247, 251))
    draw = ImageDraw.Draw(img)
    draw.rectangle((20, 20, 880, 540), outline=(40, 48, 106), width=4)
    draw.text((50, 50), BANNER, fill=(160, 0, 0))
    draw.text((50, 100), "Synthetic identity card - Name: Test Person A - ID: TEST-0000-0001", fill=(20, 25, 53))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def write_demo_files(out: Path) -> list[tuple[Path, str]]:
    out.mkdir(parents=True, exist_ok=True)
    statement = [
        "Synthetic Bank - Account statement", "Account holder: Test Person A", "Account: TEST-ACCT-0001",
        "Period: 2026-01-01 to 2026-01-31", "Closing balance: 1,234.56 (synthetic)",
    ]
    identity = [
        "Synthetic identity form (fictional)", "Full name: Test Person Alpha", "Date of birth: 03 March 1990",
        "National ID: test-0001-ab", "Document number: SYN 000123", "Issue date: 2024-01-15",
        "Expiry date: 14/01/2034", "Address: 1 Synthetic Street", "Testville", "TS1 0AA",
    ]
    files: list[tuple[str, bytes, str]] = [
        ("synthetic-identity-form.pdf", _pdf(identity), "extraction: every field type, text layer"),
        ("synthetic-identity-rotated.pdf", _pdf(identity, rotation=90), "extraction: page rotated 90 degrees"),
        ("synthetic-invalid-date.pdf", _pdf(["Full name: Test Person Beta", "Date of birth: 31/02/2026",
                                             "Issue date: 03/04/2026"]), "extraction: invalid + ambiguous dates"),
        ("synthetic-bank-statement.pdf", _pdf(statement, pages=2), "valid PDF with text layer -> ready"),
        ("synthetic-application-form.pdf", _pdf(["Synthetic application form", "Applicant: Test Person A"]),
         "valid PDF -> ready"),
        ("synthetic-scanned-letter.pdf", _pdf([], pages=1, text=False), "PDF without text layer -> OCR note"),
        ("synthetic-id-card.png", _png(), "valid PNG -> ready (OCR note)"),
        ("synthetic-with-javascript.pdf", _pdf(["Contains a JavaScript action"], javascript=True),
         "PDF with JavaScript -> needs review"),
        ("synthetic-png-renamed.pdf", _png(), "PNG named .pdf -> rejected (extension mismatch)"),
        ("synthetic-not-a-document.pdf", b"This is plain text pretending to be a PDF.\n",
         "text named .pdf -> rejected (unsupported content)"),
    ]
    written = []
    for name, data, purpose in files:
        path = out / name
        path.write_bytes(data)
        written.append((path, purpose))
    return written
