"""OCR engine interface.

``TesseractEngine`` is the real implementation (pytesseract + a local Tesseract binary).
When Tesseract is not installed, ``get_ocr_engine`` returns ``UnavailableOcrEngine``. It never
produces text; pages that need OCR are recorded with ``ocr_status = "unavailable"``.
Tests inject deterministic engines through the same interface.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from PIL import Image

from app.core.config import get_settings

logger = logging.getLogger("verifyflow.ocr")


@dataclass(frozen=True)
class OcrWord:
    text: str
    # Pixel box in the image passed to recognize().
    left: float
    top: float
    width: float
    height: float
    confidence: float  # 0..100
    line_key: str  # words sharing a key belong to the same text line


@dataclass
class OcrResult:
    words: list[OcrWord] = field(default_factory=list)

    @property
    def mean_confidence(self) -> float | None:
        return sum(w.confidence for w in self.words) / len(self.words) if self.words else None


class OcrUnavailable(RuntimeError):
    pass


class OcrFailed(RuntimeError):
    pass


@runtime_checkable
class OcrEngine(Protocol):
    name: str  # includes version; part of the extraction idempotency key

    def available(self) -> bool: ...

    def recognize(self, image: Image.Image) -> OcrResult: ...


class UnavailableOcrEngine:
    name = "none"

    def __init__(self, reason: str = "Tesseract is not installed on this server"):
        self.reason = reason

    def available(self) -> bool:
        return False

    def recognize(self, image: Image.Image) -> OcrResult:
        raise OcrUnavailable(self.reason)


class TesseractEngine:
    def __init__(self, binary: str, lang: str = "eng", timeout: int = 120):
        import pytesseract

        self._pt = pytesseract
        self._pt.pytesseract.tesseract_cmd = binary
        self.lang = lang
        self.timeout = timeout
        self.name = f"tesseract-{self._pt.get_tesseract_version()}-{lang}"

    def available(self) -> bool:
        return True

    def recognize(self, image: Image.Image) -> OcrResult:
        try:
            data = self._pt.image_to_data(
                image, lang=self.lang, output_type=self._pt.Output.DICT, timeout=self.timeout, config="--psm 3"
            )
        except Exception as exc:  # noqa: BLE001 - surfaced as an explicit OCR failure on the page
            raise OcrFailed(f"Tesseract failed: {exc}") from None
        words: list[OcrWord] = []
        for i, text in enumerate(data["text"]):
            conf = float(data["conf"][i])
            if not text.strip() or conf < 0:
                continue
            words.append(
                OcrWord(
                    text=text,
                    left=data["left"][i],
                    top=data["top"][i],
                    width=data["width"][i],
                    height=data["height"][i],
                    confidence=conf,
                    line_key=f"{data['block_num'][i]}.{data['par_num'][i]}.{data['line_num'][i]}",
                )
            )
        return OcrResult(words)


def get_ocr_engine() -> OcrEngine:
    """FastAPI dependency / factory. Never raises; falls back to the explicit unavailable engine."""
    settings = get_settings()
    binary = settings.tesseract_cmd or shutil.which("tesseract")
    if not binary:
        return UnavailableOcrEngine()
    try:
        return TesseractEngine(binary)
    except Exception as exc:  # noqa: BLE001 - reported as unavailable with the reason
        logger.warning("Tesseract at %s is not usable: %s", binary, exc)
        return UnavailableOcrEngine(f"Tesseract at {binary} could not run: {exc}")
