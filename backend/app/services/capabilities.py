"""Honest runtime capability detection, surfaced to the UI so it never implies unsupported features."""

from __future__ import annotations

import shutil
from functools import lru_cache

from app.core.config import get_settings
from app.integrations.ai.registry import get_provider
from app.schemas.system import CapabilitiesOut, CapabilityOut


def _pymupdf() -> CapabilityOut:
    try:
        import pymupdf

        return CapabilityOut(
            key="pdf_text", label="PDF text extraction", available=True,
            detail=f"PyMuPDF {pymupdf.VersionBind}",
        )
    except ImportError as exc:
        return CapabilityOut(key="pdf_text", label="PDF text extraction", available=False, detail=str(exc))


def _tesseract() -> CapabilityOut:
    settings = get_settings()
    binary = settings.tesseract_cmd or shutil.which("tesseract")
    if not binary:
        return CapabilityOut(
            key="ocr", label="OCR for scanned documents", available=False,
            detail="Tesseract binary not found. Install Tesseract or set VERIFYFLOW_TESSERACT_CMD.",
        )
    try:
        import pytesseract

        pytesseract.pytesseract.tesseract_cmd = binary
        version = str(pytesseract.get_tesseract_version())
    except Exception as exc:  # noqa: BLE001 - reported to caller, not swallowed
        return CapabilityOut(
            key="ocr", label="OCR for scanned documents", available=False,
            detail=f"Tesseract found at {binary} but failed to run: {exc}",
        )
    return CapabilityOut(key="ocr", label="OCR for scanned documents", available=True, detail=f"Tesseract {version}")


def _signature_trust() -> CapabilityOut:
    """Signatures are checked with pyHanko; a chain can only be called trusted against configured trust anchors."""
    from app.trust import anchors

    settings = get_settings()
    label = "Cryptographic signature trust validation"
    try:
        import pyhanko  # noqa: F401
    except ImportError as exc:
        return CapabilityOut(
            key="digital_signature_validation", label=label, available=False, detail=f"pyHanko missing: {exc}"
        )
    roots = anchors.load(settings.trust_roots_dir, None).roots if settings.trust_roots_dir else []
    if not roots:
        return CapabilityOut(
            key="digital_signature_validation", label=label, available=False,
            detail="No trust anchors configured (VERIFYFLOW_TRUST_ROOTS_DIR). Signatures are still checked for "
                   "integrity, but no signer is reported as trusted.",
        )
    synthetic = any("SYNTHETIC" in c.subject.human_friendly.upper() for c in roots)
    return CapabilityOut(
        key="digital_signature_validation", label=label, available=True,
        detail=f"pyHanko with {len(roots)} trust anchor(s)"
               + (" — synthetic development root, not for real documents." if synthetic else "."),
    )


@lru_cache(maxsize=1)
def ocr_available() -> bool:
    """Cached for the process lifetime: installing Tesseract requires a restart to be picked up."""
    return _tesseract().available


def get_capabilities() -> CapabilitiesOut:
    settings = get_settings()
    provider = get_provider()
    status = provider.status()
    caps = [
        _pymupdf(),
        _tesseract(),
        CapabilityOut(key="ai_explanations", label="AI explanations", available=status.enabled, detail=status.detail),
        _signature_trust(),
    ]
    return CapabilitiesOut(
        environment=settings.environment,
        version=settings.app_version,
        ai_provider_configured=settings.ai_provider,
        ai_provider_active=provider.name,
        ai_enabled=status.enabled,
        capabilities=caps,
    )
