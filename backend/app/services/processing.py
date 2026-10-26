"""Document processing job: intake inspection followed by extraction.

Steps (all deterministic, no AI):
1. Read the stored file and verify it against its recorded SHA-256 (a mismatch fails the job).
2. Inspection: PDF page count, text layer, embedded files, JavaScript, metadata, repair status; image facts.
3. Extraction (``app.extraction``): per-page text (text layer or OCR), then configured fields via the
   baseline extractor, with coordinates, raw and normalized values and quality metadata.

Concurrency and idempotency:
- A partial unique index allows at most one queued/running job per document.
- A job is *claimed* with a conditional UPDATE (queued -> running); a second runner gets 0 rows and stops.
- Work happens with no transaction open; results are committed in ONE transaction, and only if the job is
  still "running" (a job superseded by a stale-retry finds 0 rows and its results are discarded).
- Extraction is keyed by (file hash, extractor version, definitions hash, OCR engine). Unless the job is
  forced, an existing run with the same key is reused instead of recomputed.

Execution (``VERIFYFLOW_PROCESSING_MODE``):
- inline (default, local development): an in-process background task. A job interrupted by a restart stays
  "running" until detected as stale and retried (see ``document_service.retry``).
- worker (production): the API only queues the job; ``python -m app.cli worker`` claims and runs queued jobs from the
  database and re-queues interrupted ones (see ``app.services.worker``).
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
import secrets

import pymupdf
from PIL import Image
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.base import utcnow
from app.extraction import baseline, pipeline
from app.extraction.definitions import DefinitionsError, load_definitions
from app.extraction.ocr import OcrEngine, get_ocr_engine
from app.models.application import Document, DocumentStatus, JobStatus, ProcessingJob
from app.models.extraction import DocumentPage, ExtractedField, ExtractionRun
from app.services import application_service, audit_service
from app.services.audit_service import AuditContext
from app.services.storage import LocalStorage

logger = logging.getLogger("verifyflow.processing")

_JS_RE = re.compile(rb"/(JS|JavaScript)\b")
_MAX_XREFS_SCANNED = 20_000


class InspectionError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _inspect_pdf(data: bytes) -> dict:
    with pymupdf.open(stream=data, filetype="pdf") as doc:  # in memory: never holds a handle on stored files
        pages_without_text = [i + 1 for i, page in enumerate(doc) if not page.get_text("text").strip()]
        javascript = False
        unreadable_objects = 0  # malformed objects cannot be scanned; counted and reported, not hidden
        for xref in range(1, min(doc.xref_length(), _MAX_XREFS_SCANNED)):
            try:
                obj = doc.xref_object(xref, compressed=False).encode("latin-1", "replace")
            except Exception:  # noqa: BLE001
                unreadable_objects += 1
                continue  # noqa: S112
            if _JS_RE.search(obj):
                javascript = True
                break
        meta = {k: v for k, v in (doc.metadata or {}).items() if v}
        return {
            "kind": "pdf",
            "page_count": doc.page_count,
            "pages_without_text": pages_without_text,
            "text_layer": "none"
            if len(pages_without_text) == doc.page_count
            else "partial"
            if pages_without_text
            else "full",
            "embedded_files": doc.embfile_count(),
            "javascript": javascript,
            "repaired": bool(getattr(doc, "is_repaired", False)),
            "unreadable_objects": unreadable_objects,
            "metadata": meta,
        }


def _inspect_image(data: bytes) -> dict:
    with Image.open(io.BytesIO(data)) as img:
        return {
            "kind": "image",
            "format": img.format,
            "width": img.width,
            "height": img.height,
            "mode": img.mode,
            "frames": getattr(img, "n_frames", 1),
        }


def assess(result: dict, ocr: bool) -> tuple[str, list[dict]]:
    """Turn raw inspection facts into a status plus human-readable findings."""
    findings: list[dict] = []
    review = False
    if result["kind"] == "pdf":
        if result["javascript"]:
            review = True
            findings.append(
                {
                    "severity": "warning",
                    "code": "pdf_javascript",
                    "message": "The PDF contains JavaScript. It was not executed; review the file's origin.",
                }
            )
        if result["embedded_files"]:
            review = True
            n = result["embedded_files"]
            findings.append(
                {
                    "severity": "warning",
                    "code": "pdf_embedded_files",
                    "message": f"The PDF carries {n} embedded file(s), which were not inspected.",
                }
            )
        if result["repaired"]:
            review = True
            findings.append(
                {
                    "severity": "warning",
                    "code": "pdf_repaired",
                    "message": "The PDF's internal structure was damaged and had to be repaired to be read.",
                }
            )
        if result.get("unreadable_objects"):
            review = True
            findings.append(
                {
                    "severity": "warning",
                    "code": "pdf_unreadable_objects",
                    "message": f"{result['unreadable_objects']} internal PDF object(s) could not be read "
                    "and were not checked for active content.",
                }
            )
        if result["text_layer"] != "full":
            scope = "No page" if result["text_layer"] == "none" else f"{len(result['pages_without_text'])} page(s)"
            verb = "has" if result["text_layer"] == "none" else "have"
            findings.append(
                {
                    "severity": "info",
                    "code": "ocr_required",
                    "message": f"{scope} {verb} no text layer; text must come from OCR."
                    + ("" if ocr else " OCR is not available on this server."),
                }
            )
    else:
        findings.append(
            {
                "severity": "info",
                "code": "ocr_required",
                "message": "Images have no text layer; text must come from OCR."
                + ("" if ocr else " OCR is not available on this server."),
            }
        )
    return (DocumentStatus.NEEDS_REVIEW.value if review else DocumentStatus.READY.value), findings


def _claim(session_factory: sessionmaker, job_id: str) -> dict | None:
    """Atomically move a queued job to running. Returns a snapshot of what the worker needs, or None."""
    with session_factory() as db:
        claimed = db.execute(
            update(ProcessingJob)
            .where(ProcessingJob.id == job_id, ProcessingJob.status == JobStatus.QUEUED.value)
            .values(status=JobStatus.RUNNING.value, started_at=utcnow())
            .execution_options(synchronize_session=False)
        ).rowcount
        if claimed != 1:
            db.rollback()
            return None
        job = db.get(ProcessingJob, job_id)
        assert job is not None
        doc = job.document
        doc.status = DocumentStatus.PROCESSING.value
        db.commit()
        return {
            "document_id": doc.id,
            "storage_key": doc.storage_key,
            "sha256": doc.sha256,
            "mime": doc.detected_mime,
            "document_type": doc.document_type,
            "force": job.force,
            "filename": doc.original_filename,
        }


def _reusable_run(session_factory: sessionmaker, document_id: str, key: str) -> str | None:
    with session_factory() as db:
        return db.execute(
            select(ExtractionRun.id)
            .where(ExtractionRun.document_id == document_id, ExtractionRun.idempotency_key == key)
            .order_by(ExtractionRun.finished_at.desc())
            .limit(1)
        ).scalar_one_or_none()


def _persist_run(
    db: Session,
    document_id: str,
    job_id: str,
    snap: dict,
    outcome: pipeline.ExtractionOutcome,
    *,
    defs_hash: str,
    engine_name: str,
    key: str,
    started_at,  # noqa: ANN001
) -> ExtractionRun:
    run = ExtractionRun(
        document_id=document_id,
        job_id=job_id,
        status=outcome.status,
        is_current=True,
        extractor=baseline.EXTRACTOR,
        extractor_version=baseline.VERSION,
        definitions_hash=defs_hash,
        ocr_engine=engine_name,
        input_sha256=snap["sha256"],
        idempotency_key=key,
        started_at=started_at,
        finished_at=utcnow(),
        summary=outcome.summary,
    )
    db.add(run)
    db.flush()
    for page in outcome.pages:
        db.add(
            DocumentPage(
                run_id=run.id,
                page_number=page.page_number,
                width=round(page.width, 3),
                height=round(page.height, 3),
                rotation=page.rotation,
                units=page.units,
                text_source=page.text_source,
                text_layer_quality=page.text_layer_quality,
                ocr_status=page.ocr_status,
                ocr_confidence=None if page.ocr_confidence is None else round(page.ocr_confidence, 2),
                char_count=page.char_count,
                raw_text=page.raw_text,
                normalized_text=page.normalized_text,
                warnings=page.warnings,
            )
        )
    for position, f in enumerate(outcome.fields):
        db.add(
            ExtractedField(
                run_id=run.id,
                document_id=document_id,
                position=position,
                field_key=f.definition.key,
                field_type=f.definition.type.value,
                label=f.definition.label,
                status=f.status,
                raw_value=f.raw_value,
                normalized_value=f.normalized_value,
                normalized_data=f.normalized_data,
                normalization_note=f.note,
                method=f.method,
                matched_label=f.matched_label,
                page_number=f.page_number,
                bbox=f.bbox,
                confidence=f.confidence,
                quality_flags=f.flags,
                alternatives=f.alternatives,
            )
        )
    return run


def _make_current(db: Session, document_id: str, run_id: str | None = None) -> None:
    """Clear the current flag on every other run of the document (before inserting/marking the new one)."""
    stmt = update(ExtractionRun).where(ExtractionRun.document_id == document_id, ExtractionRun.is_current.is_(True))
    if run_id:
        stmt = stmt.where(ExtractionRun.id != run_id)
    db.execute(stmt.values(is_current=False).execution_options(synchronize_session=False))


def schedule(background, job_id: str, session_factory: sessionmaker, storage: LocalStorage,  # noqa: ANN001
             request_id: str | None, ocr_engine: OcrEngine | None) -> None:
    """Start a queued job in this process (inline mode). In worker mode the job stays queued for the worker."""
    if get_settings().processing_mode == "inline":
        background.add_task(run_job, job_id, session_factory, storage, request_id, ocr_engine)


def run_job(
    job_id: str,
    session_factory: sessionmaker,
    storage: LocalStorage,
    request_id: str | None = None,
    ocr_engine: OcrEngine | None = None,
) -> None:
    """Execute one queued job. Never raises: every failure is recorded on the job."""
    snap = _claim(session_factory, job_id)
    if snap is None:
        return  # not queued (already running, finished or superseded): nothing to do
    engine = ocr_engine or get_ocr_engine()
    settings = get_settings()
    started_at = utcnow()

    error: tuple[str, str] | None = None
    facts: dict = {}
    findings: list[dict] = []
    inspect_status = DocumentStatus.READY.value
    outcome: pipeline.ExtractionOutcome | None = None
    reused_run: str | None = None
    defs_hash = key = ""
    try:
        data = storage.read(snap["storage_key"])
        if not secrets.compare_digest(hashlib.sha256(data).hexdigest(), snap["sha256"]):
            raise InspectionError("integrity_mismatch", "The stored file no longer matches its SHA-256 hash")
        facts = _inspect_pdf(data) if snap["mime"] == "application/pdf" else _inspect_image(data)
        inspect_status, findings = assess(facts, engine.available())
        definitions, defs_hash = load_definitions(settings.field_definitions_path)
        key = pipeline.idempotency_key(snap["sha256"], defs_hash, engine.name)
        if not snap["force"]:
            reused_run = _reusable_run(session_factory, snap["document_id"], key)
        if reused_run is None:
            outcome = pipeline.run(
                data, snap["mime"], snap["document_type"], definitions, engine, settings.ocr_max_pages
            )
    except InspectionError as exc:
        error = (exc.code, str(exc))
    except DefinitionsError as exc:
        logger.error("Field definitions are invalid: %s", exc)
        error = ("definitions_invalid", str(exc))
    except Exception as exc:  # noqa: BLE001 - recorded on the job and logged, never swallowed
        logger.exception("Processing job %s failed", job_id)
        error = ("processing_error", f"{type(exc).__name__}: {exc}"[:2000])

    with session_factory() as db:
        result: dict = {"facts": facts, "findings": findings}
        values: dict = {"finished_at": utcnow()}
        if error:
            values.update(status=JobStatus.FAILED.value, error_code=error[0], error_message=error[1], result=result)
        else:
            values.update(status=JobStatus.SUCCEEDED.value, result=result)
        owned = db.execute(
            update(ProcessingJob)
            .where(ProcessingJob.id == job_id, ProcessingJob.status == JobStatus.RUNNING.value)
            .values(**values)
            .execution_options(synchronize_session=False)
        ).rowcount
        if owned != 1:
            db.rollback()
            logger.warning("Job %s no longer owns its document (superseded); its results were discarded", job_id)
            return

        doc = db.get(Document, snap["document_id"])
        assert doc is not None
        audit_data: dict = {"document_id": doc.id, "job_id": job_id}
        if error:
            doc.status = DocumentStatus.FAILED.value
            outcome_label, summary = "failure", f"Processing failed for “{doc.original_filename}”: {error[0]}"
            audit_data["error_code"] = error[0]
        else:
            if reused_run:
                _make_current(db, doc.id, reused_run)
                db.execute(update(ExtractionRun).where(ExtractionRun.id == reused_run).values(is_current=True))
                prior = db.get(ExtractionRun, reused_run)
                assert prior is not None
                run_needs_review = bool(
                    prior.summary.get("fields_needing_attention") or prior.summary.get("pages_needing_attention")
                )
                run_id = reused_run
            else:
                assert outcome is not None
                _make_current(db, doc.id)
                run = _persist_run(
                    db,
                    doc.id,
                    job_id,
                    snap,
                    outcome,
                    defs_hash=defs_hash,
                    engine_name=engine.name,
                    key=key,
                    started_at=started_at,
                )
                run_needs_review = outcome.needs_review
                run_id = run.id
            needs_review = inspect_status == DocumentStatus.NEEDS_REVIEW.value or bool(run_needs_review)
            doc.status = DocumentStatus.NEEDS_REVIEW.value if needs_review else DocumentStatus.READY.value
            if facts.get("page_count"):
                doc.page_count = facts["page_count"]
            result["extraction"] = {"run_id": run_id, "reused": bool(reused_run)}
            db.execute(update(ProcessingJob).where(ProcessingJob.id == job_id).values(result=result))
            outcome_label, summary = "success", f"Processed “{doc.original_filename}”: {doc.status}"
            audit_data.update(status=doc.status, extraction_run_id=run_id, reused_run=bool(reused_run))
        application_service.settle_after_processing(db, doc.application)
        audit_service.record(
            db,
            AuditContext(request_id=request_id),
            "document.processed",
            entity_type="application",
            entity_id=doc.application_id,
            outcome=outcome_label,
            summary=summary,
            data=audit_data,
        )
        db.commit()
