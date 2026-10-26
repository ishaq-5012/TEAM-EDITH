"""Durable processing worker (``VERIFYFLOW_PROCESSING_MODE=worker``).

Jobs are rows in ``processing_jobs``, so the queue is the database itself: nothing is lost when the API or the worker
restarts. Each pass:

1. Recovers interrupted jobs: a job still "running" after ``processing_stale_minutes`` is marked failed
   (``interrupted``) and, below ``processing_max_attempts``, a new queued attempt is created in the same transaction.
   At the limit the document is left failed for a person to retry. Each recovery is audited.
2. Runs queued jobs oldest first through ``processing.run_job``. Claiming is a conditional UPDATE, so several workers
   can poll the same database without running a job twice.

A slow job that is recovered while still alive cannot overwrite the newer attempt: ``run_job`` commits results only
while its own job row is still "running".
"""

from __future__ import annotations

import logging
import threading
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.db.base import utcnow
from app.extraction.ocr import OcrEngine
from app.models.application import Document, DocumentStatus, JobStatus, ProcessingJob
from app.services import audit_service, processing
from app.services.audit_service import AuditContext
from app.services.document_service import PROCESSING_JOB
from app.services.storage import LocalStorage

logger = logging.getLogger("verifyflow.worker")


def recover_stale(session_factory: sessionmaker) -> int:
    """Fail interrupted jobs and queue a further attempt where allowed. Returns how many jobs were recovered."""
    settings = get_settings()
    cutoff = utcnow() - timedelta(minutes=settings.processing_stale_minutes)
    recovered = 0
    with session_factory() as db:
        stale = db.execute(
            select(ProcessingJob)
            .where(ProcessingJob.status == JobStatus.RUNNING.value, ProcessingJob.started_at < cutoff)
            .order_by(ProcessingJob.started_at)
        ).scalars().all()
        for job in stale:
            doc: Document = job.document
            job.status = JobStatus.FAILED.value
            job.finished_at = utcnow()
            job.error_code = "interrupted"
            job.error_message = "Processing did not finish (worker restart or crash) and was recovered by the worker"
            db.flush()  # the one-active-job index must see this job leave "running" before a new one is inserted
            requeue = job.attempt < settings.processing_max_attempts
            if requeue:
                db.add(ProcessingJob(document_id=doc.id, kind=PROCESSING_JOB, force=job.force, attempt=job.attempt + 1))
                doc.status = DocumentStatus.QUEUED.value
            else:
                doc.status = DocumentStatus.FAILED.value
            audit_service.record(
                db, AuditContext(request_id=None), "document.processing_recovered",
                entity_type="application", entity_id=doc.application_id, outcome="success" if requeue else "failure",
                summary=(
                    f"Worker re-queued interrupted processing of “{doc.original_filename}” (attempt {job.attempt + 1})"
                    if requeue
                    else f"Processing of “{doc.original_filename}” was interrupted {job.attempt} times; left failed"
                ),
                data={"document_id": doc.id, "job_id": job.id, "attempt": job.attempt, "requeued": requeue},
            )
            recovered += 1
        db.commit()
    if recovered:
        logger.warning("Recovered %d interrupted processing job(s)", recovered)
    return recovered


def queued_job_ids(session_factory: sessionmaker, limit: int) -> list[str]:
    with session_factory() as db:
        return list(
            db.execute(
                select(ProcessingJob.id)
                .where(ProcessingJob.status == JobStatus.QUEUED.value)
                .order_by(ProcessingJob.created_at)
                .limit(limit)
            ).scalars()
        )


def run_once(
    session_factory: sessionmaker, storage: LocalStorage, ocr_engine: OcrEngine | None = None, batch: int = 10
) -> int:
    """One pass: recover stale jobs, then run up to ``batch`` queued jobs. Returns how many jobs were attempted."""
    recover_stale(session_factory)
    ids = queued_job_ids(session_factory, batch)
    for job_id in ids:
        processing.run_job(job_id, session_factory, storage, None, ocr_engine)
    return len(ids)


def run_forever(
    session_factory: sessionmaker, storage: LocalStorage, stop: threading.Event, ocr_engine: OcrEngine | None = None
) -> None:
    """Poll until ``stop`` is set. A pass that raises is logged and retried after the poll interval."""
    interval = get_settings().worker_poll_seconds
    logger.info("Processing worker started (poll every %.1fs)", interval)
    while not stop.is_set():
        try:
            busy = run_once(session_factory, storage, ocr_engine)
        except Exception:  # noqa: BLE001 - a database outage must not kill the worker; it is logged and retried
            logger.exception("Worker pass failed; retrying in %.1fs", interval)
            busy = 0
        if not busy:
            stop.wait(interval)
    logger.info("Processing worker stopped")
