"""Read every page of a document into words with coordinates in *displayed* page space.

Coordinate contract (relied on by the frontend highlighter and by tests):
- origin top-left, x to the right, y downwards
- the page as displayed: PDF ``/Rotate`` is applied, so a 90°-rotated A4 page is 842 × 595 pt
- PDFs are in points, images in pixels after EXIF orientation is applied
PyMuPDF reports words in the *unrotated* page space; they are mapped with ``page.rotation_matrix``.
OCR runs on a rendering of the displayed page, so its pixel boxes are divided by the render scale.
"""

from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass, field

import pymupdf
from PIL import Image, ImageOps

from app.extraction.ocr import OcrEngine, OcrFailed, OcrUnavailable
from app.models.extraction import OcrStatus, TextSource

OCR_DPI = 300
OCR_SCALE = OCR_DPI / 72
LOW_CONFIDENCE = 60.0  # mean Tesseract word confidence below this is "low"
MIN_GOOD_CHARS = 20


@dataclass(frozen=True)
class Word:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    line_key: str
    confidence: float | None = None  # OCR only


@dataclass
class PageContent:
    page_number: int
    width: float
    height: float
    rotation: int
    units: str
    words: list[Word]
    raw_text: str
    text_source: str
    text_layer_quality: str
    ocr_status: str
    ocr_confidence: float | None = None
    warnings: list[dict] = field(default_factory=list)

    @property
    def normalized_text(self) -> str:
        return normalize_text(self.raw_text)

    @property
    def char_count(self) -> int:
        return sum(1 for c in self.raw_text if not c.isspace())


def normalize_text(raw: str) -> str:
    """Whitespace normalization for display/search. Never used to overwrite raw text.

    NFC, unified line endings, runs of spaces/tabs collapsed, trailing spaces trimmed, blank-line runs collapsed.
    """
    text = unicodedata.normalize("NFC", raw).replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t\f\v ]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def assess_text_layer(text: str) -> str:
    """Classify a PDF text layer: none | unusable | sparse | good.

    "unusable" catches garbled layers (broken font encodings) that would poison extraction:
    many replacement/private-use/control characters, or too few letters and digits.
    """
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return "none"
    bad = sum(1 for c in chars if c == "�" or unicodedata.category(c) in ("Co", "Cc", "Cs", "Cn"))
    alnum = sum(1 for c in chars if c.isalnum())
    if bad / len(chars) > 0.1 or alnum / len(chars) < 0.5:
        return "unusable"
    if len(chars) < MIN_GOOD_CHARS:
        return "sparse"
    return "good"


def _warning(code: str, message: str) -> dict:
    return {"code": code, "message": message}


def _ocr_words(
    engine: OcrEngine, image: Image.Image, scale: float, page_number: int
) -> tuple[list[Word], float | None]:
    result = engine.recognize(image)
    words = [
        Word(
            text=w.text,
            x0=w.left / scale,
            y0=w.top / scale,
            x1=(w.left + w.width) / scale,
            y1=(w.top + w.height) / scale,
            line_key=f"ocr:{page_number}:{w.line_key}",
            confidence=w.confidence,
        )
        for w in result.words
    ]
    return words, result.mean_confidence


def _lines_text(words: list[Word]) -> str:
    lines: dict[str, list[str]] = {}
    for w in words:
        lines.setdefault(w.line_key, []).append(w.text)
    return "\n".join(" ".join(ws) for ws in lines.values())


def _apply_ocr(page: PageContent, engine: OcrEngine, image_factory, ocr_budget: list[int]) -> None:  # noqa: ANN001
    """Run OCR for a page that needs it, recording every outcome explicitly."""
    if not engine.available():
        page.ocr_status = OcrStatus.UNAVAILABLE.value
        page.warnings.append(
            _warning("ocr_unavailable", "This page has no usable text layer and OCR is not available on this server.")
        )
        return
    if ocr_budget[0] <= 0:
        page.ocr_status = OcrStatus.SKIPPED_LIMIT.value
        page.warnings.append(
            _warning("ocr_page_limit", "OCR was skipped: the per-document OCR page limit was reached.")
        )
        return
    ocr_budget[0] -= 1
    try:
        image, scale = image_factory()
        words, confidence = _ocr_words(engine, image, scale, page.page_number)
    except (OcrFailed, OcrUnavailable) as exc:
        page.ocr_status = OcrStatus.FAILED.value
        page.warnings.append(_warning("ocr_failed", str(exc)))
        return
    if not words:
        page.ocr_status = OcrStatus.FAILED.value
        page.warnings.append(_warning("ocr_no_text", "OCR ran but recognised no text on this page."))
        return
    page.words, page.raw_text, page.text_source = words, _lines_text(words), TextSource.OCR.value
    page.ocr_confidence = confidence
    if confidence is not None and confidence < LOW_CONFIDENCE:
        page.ocr_status = OcrStatus.LOW_CONFIDENCE.value
        page.warnings.append(
            _warning(
                "ocr_low_confidence",
                f"OCR confidence is low ({confidence:.0f}/100); values may contain recognition errors.",
            )
        )
    else:
        page.ocr_status = OcrStatus.COMPLETED.value


def read_pdf(data: bytes, engine: OcrEngine, max_ocr_pages: int) -> list[PageContent]:
    pages: list[PageContent] = []
    budget = [max_ocr_pages]
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        for index, pdf_page in enumerate(doc):
            number = index + 1
            matrix = pdf_page.rotation_matrix
            words = []
            for x0, y0, x1, y1, text, block, line, _ in pdf_page.get_text("words", sort=False):
                r = pymupdf.Rect(x0, y0, x1, y1) * matrix
                words.append(Word(text, r.x0, r.y0, r.x1, r.y1, f"pdf:{number}:{block}.{line}"))
            raw = pdf_page.get_text("text")
            quality = assess_text_layer(raw)
            page = PageContent(
                page_number=number,
                width=pdf_page.rect.width,
                height=pdf_page.rect.height,
                rotation=pdf_page.rotation,
                units="pt",
                words=words,
                raw_text=raw,
                text_source=TextSource.TEXT_LAYER.value if quality in ("good", "sparse") else TextSource.NONE.value,
                text_layer_quality=quality,
                ocr_status=OcrStatus.NOT_NEEDED.value,
            )
            if quality == "unusable":
                page.words, page.raw_text = [], ""  # garbled layer must not feed extraction
                page.warnings.append(
                    _warning("text_layer_unusable", "The text layer is garbled (broken font encoding); it was ignored.")
                )
            if quality in ("none", "unusable"):

                def render(p: pymupdf.Page = pdf_page) -> tuple[Image.Image, float]:
                    pix = p.get_pixmap(matrix=pymupdf.Matrix(OCR_SCALE, OCR_SCALE), alpha=False)
                    return Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB"), OCR_SCALE

                _apply_ocr(page, engine, render, budget)
            elif quality == "sparse":
                page.warnings.append(
                    _warning("text_layer_sparse", "Very little selectable text on this page; parts may be scanned.")
                )
            pages.append(page)
    return pages


def load_image(data: bytes) -> Image.Image:
    with Image.open(io.BytesIO(data)) as img:
        img.seek(0)
        return ImageOps.exif_transpose(img).convert("RGB")


def read_image(data: bytes, engine: OcrEngine, max_ocr_pages: int) -> list[PageContent]:
    image = load_image(data)
    page = PageContent(
        page_number=1,
        width=float(image.width),
        height=float(image.height),
        rotation=0,
        units="px",
        words=[],
        raw_text="",
        text_source=TextSource.NONE.value,
        text_layer_quality="n/a",
        ocr_status=OcrStatus.NOT_NEEDED.value,
    )
    _apply_ocr(page, engine, lambda: (image, 1.0), [max_ocr_pages])
    return [page]
