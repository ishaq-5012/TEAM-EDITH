from __future__ import annotations

import logging
from datetime import UTC, timedelta
from pathlib import Path
from typing import Annotated

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text

from app.api.deps import DbSession, require_permission
from app.core.config import get_settings
from app.core.roles import Permission
from app.db.base import utcnow
from app.models.application import JobStatus, ProcessingJob
from app.models.user import User
from app.schemas.system import CapabilitiesOut, HealthOut, ProcessingHealthOut, ReadinessOut
from app.services.capabilities import get_capabilities
from app.services.storage import LocalStorage, get_storage

router = APIRouter(tags=["system"])
Storage = Annotated[LocalStorage, Depends(get_storage)]
logger = logging.getLogger("verifyflow")


@router.get("/health", response_model=HealthOut)
def health(db: DbSession) -> JSONResponse:
    version = get_settings().app_version
    try:
        db.execute(text("SELECT 1"))
        body = HealthOut(status="ok", database="ok", version=version)
        return JSONResponse(body.model_dump())
    except Exception:
        logger.exception("Health check database probe failed")
        body = HealthOut(status="degraded", database="error", version=version)
        return JSONResponse(body.model_dump(), status_code=503)


def _head_revision() -> str:
    backend = Path(__file__).resolve().parents[3]
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "alembic"))
    return ScriptDirectory.from_config(cfg).get_current_head() or ""


@router.get("/health/ready", response_model=ReadinessOut)
def readiness(db: DbSession, storage: Storage) -> JSONResponse:
    """For load balancers and monitors: 503 unless the database answers, the schema is at the latest migration and
    private storage is writable. Reports the processing backlog (counts only) so a stopped worker is visible."""
    settings = get_settings()
    database = migrations = store = "error"
    processing: ProcessingHealthOut | None = None
    try:
        db.execute(text("SELECT 1"))
        database = "ok"
        current = db.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
        migrations = "ok" if current == _head_revision() else "behind"
        jobs = ProcessingJob.status
        queued, oldest = db.execute(
            select(func.count(), func.min(ProcessingJob.created_at)).where(jobs == JobStatus.QUEUED.value)
        ).one()
        cutoff = utcnow() - timedelta(minutes=settings.processing_stale_minutes)
        stale = db.execute(
            select(func.count()).where(jobs == JobStatus.RUNNING.value, ProcessingJob.started_at < cutoff)
        ).scalar_one()
        if oldest is not None and oldest.tzinfo is None:
            oldest = oldest.replace(tzinfo=UTC)
        processing = ProcessingHealthOut(
            mode=settings.processing_mode, queued=queued, stale_running=stale,
            oldest_queued_seconds=int((utcnow() - oldest).total_seconds()) if oldest else None,
        )
    except Exception:
        logger.exception("Readiness probe: database check failed")
    try:
        storage.check_writable()
        store = "ok"
    except Exception:
        logger.exception("Readiness probe: storage is not writable")
    ok = database == "ok" and migrations == "ok" and store == "ok"
    body = ReadinessOut(
        status="ok" if ok else "degraded", version=settings.app_version, database=database, migrations=migrations,
        storage=store, processing=processing,
    )
    return JSONResponse(body.model_dump(), status_code=200 if ok else 503)


@router.get("/system/capabilities", response_model=CapabilitiesOut)
def capabilities(_: Annotated[User, Depends(require_permission(Permission.SYSTEM_READ))]) -> CapabilitiesOut:
    return get_capabilities()
