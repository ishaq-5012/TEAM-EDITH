"""Development-only demo data: a few applications with synthetic documents, run through the real pipeline.

Every application created here has ``is_synthetic = true`` and a title starting with "[SYNTHETIC DEMO]", so it is
labelled on every screen and can be excluded from insights. Documents are generated text (fictional people, no real
data). Nothing is invented downstream: extraction, evidence analysis and validation run exactly as for uploads, so
dashboards show what the pipeline actually produced. Validation runs only if published rules are in force (rules
need four-eyes approval and are never seeded).
"""

from __future__ import annotations

import io
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.errors import DomainError
from app.core.roles import Permission, has_permission
from app.models.user import User
from app.services import (
    application_service,
    audit_service,
    document_service,
    evidence_service,
    processing,
    validation_service,
)
from app.services.audit_service import AuditContext
from app.services.demo_files import _pdf
from app.services.storage import LocalStorage

TITLE_PREFIX = "[SYNTHETIC DEMO]"

CASES: list[tuple[str, str, list[tuple[str, list[str]]]]] = [
    ("Consistent identity", "kyc", [
        ("synthetic-id-alpha.pdf", ["Synthetic identity form (fictional)", "Full name: Test Person Alpha",
                                    "Date of birth: 03 March 1990", "National ID: SYN-ID-0001"]),
        ("synthetic-statement-alpha.pdf", ["Synthetic Bank statement (fictional)", "Account holder: Test Person Alpha",
                                           "Date of birth: 03 March 1990", "Account number: SYN-ACCT-0001"]),
    ]),
    ("Conflicting date of birth", "kyc", [
        ("synthetic-id-beta.pdf", ["Synthetic identity form (fictional)", "Full name: Test Person Beta",
                                   "Date of birth: 14 July 1985", "National ID: SYN-ID-0002"]),
        ("synthetic-letter-beta.pdf", ["Synthetic letter (fictional)", "Full name: Test Person Beta",
                                       "Date of birth: 14 July 2012"]),
    ]),
    ("Missing date of birth", "loan", [
        ("synthetic-form-gamma.pdf", ["Synthetic application form (fictional)", "Applicant: Test Person Gamma",
                                      "Address: 1 Synthetic Street"]),
    ]),
]


class SeedRefused(DomainError):
    code = "seed_refused"


def seed_demo(
    session_factory: sessionmaker, storage: LocalStorage, owner_email: str, *, evaluation_date=None  # noqa: ANN001
) -> list[dict]:
    settings = get_settings()
    if settings.environment == "production":
        raise SeedRefused("seed-demo is for development and test environments only")
    ctx_id = "cli-seed-demo"
    out: list[dict] = []
    with session_factory() as db:
        owner = _owner(db, owner_email)
        ctx = AuditContext(actor=owner, request_id=ctx_id)
        jobs: list[tuple[str, str]] = []
        for title, app_type, docs in CASES:
            app = application_service.create(
                db, ctx, owner, title=f"{TITLE_PREFIX} {title}", application_type=app_type, applicant_name=None,
                description="Synthetic demo data created by `python -m app.cli seed-demo`. Fictional people only.",
            )
            app.is_synthetic = True
            db.commit()
            for name, lines in docs:
                result = document_service.upload(
                    db, ctx, owner, storage, app.id, stream=io.BytesIO(_pdf(lines)), filename=name,
                    declared_mime="application/pdf", document_type=None,
                )
                jobs.append((app.id, result.job.id))
            out.append({"application_id": app.id, "reference": app.reference, "title": app.title})
    for _app_id, job_id in jobs:
        processing.run_job(job_id, session_factory, storage, ctx_id)
    with session_factory() as db:
        owner = _owner(db, owner_email)
        ctx = AuditContext(actor=owner, request_id=ctx_id)
        for row in out:
            evidence_service.analyze(db, ctx, owner, row["application_id"], force=False)
            try:
                run = validation_service.run(db, ctx, owner, row["application_id"],
                                             evaluation_date or datetime.now(UTC).date())
                row["validation"] = run.summary
            except DomainError as exc:
                row["validation"] = f"not run: {exc.message}"
        audit_service.record(
            db, ctx, "demo.seeded", entity_type="system", entity_id="demo",
            summary=f"Created {len(out)} synthetic demo application(s)",
            data={"applications": [r["reference"] for r in out]},
        )
        db.commit()
    return out


def _owner(db: Session, email: str) -> User:
    user = db.execute(select(User).where(User.email == email.strip().lower())).scalar_one_or_none()
    if user is None or not user.is_active:
        raise SeedRefused(f"No active user {email}")
    if not has_permission(user.role, Permission.APPLICATIONS_WRITE):
        raise SeedRefused(f"{email} can't create applications")
    return user

