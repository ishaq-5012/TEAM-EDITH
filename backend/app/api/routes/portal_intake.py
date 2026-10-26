"""Authenticated, idempotent service-to-service intake from the mock portal."""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import DbSession, audit_context
from app.core.config import get_settings
from app.core.errors import DomainError, NotFoundError, ConflictError
from app.core.roles import Role
from app.models.application import Application, Document, DocumentStatus, MemberRole
from app.models.portal_intake import PortalDocument, PortalSubmission
from app.models.review import ReviewItem, ReviewStatus
from app.models.user import User
from app.services import application_service, audit_service, document_service, evidence_service, processing, review_service, rule_service, trust_service, validation_service
from app.services.storage import LocalStorage, get_storage
from app.db.session import get_session_factory
from app.extraction.ocr import get_ocr_engine
from fastapi import BackgroundTasks
from sqlalchemy.orm import sessionmaker

router = APIRouter(prefix="/portal-intake", tags=["portal-intake"])


class ExpectedDocument(BaseModel):
    version_id: str = Field(min_length=1, max_length=64)
    document_id: str = Field(min_length=1, max_length=64)
    code: str = Field(min_length=1, max_length=60)
    version: int = Field(ge=1)
    filename: str = Field(min_length=1, max_length=255)
    mime: str = Field(min_length=1, max_length=120)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class SubmissionIn(BaseModel):
    portal_application_id: str = Field(min_length=1, max_length=64)
    submission_version: int = Field(ge=1)
    reference: str = Field(min_length=1, max_length=32)
    category_id: str = Field(min_length=1, max_length=60)
    category_name: str = Field(min_length=1, max_length=200)
    institution: dict
    form: dict[str, str]
    submitted_at: str
    documents: list[ExpectedDocument] = Field(max_length=200)


def _actor(request: Request, db: DbSession) -> User:
    settings = get_settings()
    configured = settings.portal_shared_secret.get_secret_value() if settings.portal_shared_secret else ""
    supplied = request.headers.get("x-portal-secret", "")
    if not configured or not supplied or not secrets.compare_digest(supplied, configured):
        raise DomainError("Invalid portal service credentials", code="unauthorized", status_code=401)
    owner = db.execute(select(User).where(User.email == settings.portal_owner_email, User.is_active.is_(True))).scalar_one_or_none()
    if owner is None or owner.role != Role.REVIEWER.value or owner.institution_id is None:
        raise DomainError("Portal service owner is not an active reviewer in a workspace", code="portal_not_configured", status_code=503)
    return owner


Actor = Annotated[User, Depends(_actor)]


def _submission(db, actor: User, portal_id: str, version: int) -> PortalSubmission:
    sub = db.execute(select(PortalSubmission).join(Application, Application.id == PortalSubmission.application_id).where(
        PortalSubmission.portal_application_id == portal_id, PortalSubmission.version == version,
        Application.institution_id == actor.institution_id)).scalar_one_or_none()
    if sub is None:
        raise NotFoundError("Portal submission not found")
    return sub


@router.post("/submissions")
def receive(body: SubmissionIn, request: Request, db: DbSession, actor: Actor) -> dict:
    snapshot = body.model_dump(mode="json")
    if len({d.version_id for d in body.documents}) != len(body.documents):
        raise DomainError("Duplicate document-version ID", code="invalid_submission")
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    old = db.execute(select(PortalSubmission).join(Application, Application.id == PortalSubmission.application_id).where(
        PortalSubmission.portal_application_id == body.portal_application_id,
        Application.institution_id == actor.institution_id).order_by(PortalSubmission.version.desc())).scalars().first()
    if old and old.version == body.submission_version:
        if old.payload_hash != digest:
            raise ConflictError("Submission version content differs from the first delivery", code="idempotency_conflict")
        return {"submission_id": old.id, "application_id": old.application_id, "state": old.state}
    if old and (old.version > body.submission_version or old.state != "received"):
        raise ConflictError("Previous submission must be received before another version", code="submission_order")
    if old is None and body.submission_version != 1:
        raise ConflictError("The first submission must have version 1", code="submission_order")
    if old:
        app = db.get(Application, old.application_id)
    else:
        app = Application(institution_id=actor.institution_id, owner_id=actor.id,
            reference=application_service._new_reference(db),
            title=f"{body.category_name} — {body.institution.get('name', 'Institution')}"[:200],
            application_type=body.category_id,
            applicant_name=str(body.institution.get("name", ""))[:200],
            description=f"Portal application {body.reference}; institution submission.",
            is_synthetic=True)
        db.add(app)
        db.flush()
    sub = PortalSubmission(portal_application_id=body.portal_application_id, application_id=app.id,
        version=body.submission_version, payload_hash=digest, snapshot=snapshot,
        expected_documents=len(body.documents), state="receiving")
    db.add(sub)
    db.flush()
    audit_service.record(db, audit_context(request, actor), "portal.submission_staged",
        entity_type="application", entity_id=app.id,
        data={"portal_application_id": body.portal_application_id, "version": body.submission_version,
              "submission_id": sub.id, "expected_documents": len(body.documents)})
    db.commit()
    return {"submission_id": sub.id, "application_id": app.id, "state": sub.state}


@router.put("/submissions/{portal_id}/{version}/documents/{version_id}")
async def receive_document(portal_id: str, version: int, version_id: str, request: Request,
                           background: BackgroundTasks, db: DbSession, actor: Actor,
                           storage: Annotated[LocalStorage, Depends(get_storage)],
                           factory: Annotated[sessionmaker, Depends(get_session_factory)],
                           ocr: Annotated[object, Depends(get_ocr_engine)]) -> dict:
    sub = _submission(db, actor, portal_id, version)
    expected = next((d for d in sub.snapshot["documents"] if d["version_id"] == version_id), None)
    if expected is None:
        raise NotFoundError("Document version not in this submission")
    already = db.execute(select(PortalDocument).where(PortalDocument.submission_id == sub.id, PortalDocument.portal_version_id == version_id)).scalar_one_or_none()
    if already:
        if already.submission_id != sub.id or already.sha256 != expected["sha256"]:
            raise ConflictError("Document-version ID already belongs to another payload", code="idempotency_conflict")
        return {"document_id": already.document_id, "state": "stored"}
    if sub.state != "receiving":
        raise ConflictError("Submission is closed for uploads", code="submission_closed")
    length = request.headers.get("content-length", "")
    if not length.isdigit() or int(length) > get_settings().max_upload_bytes:
        raise DomainError("Document length missing or exceeds limit", code="file_too_large", status_code=413)
    data = await request.body()
    if hashlib.sha256(data).hexdigest() != expected["sha256"]:
        raise ConflictError("Document content does not match submitted SHA-256", code="hash_mismatch")
    from io import BytesIO
    from app.services.document_service import DuplicateDocument
    try:
        result = document_service.upload(db, audit_context(request, actor), actor, storage, sub.application_id,
            stream=BytesIO(data), filename=expected["filename"], declared_mime=expected["mime"],
            document_type=expected["code"])
        doc = result.document
        processing.schedule(background, result.job.id, factory, storage, getattr(request.state, "request_id", None), ocr)
    except DuplicateDocument as exc:
        db.rollback()
        doc = db.execute(select(Document).where(Document.application_id == sub.application_id, Document.sha256 == expected["sha256"])).scalar_one()
    mapped = PortalDocument(submission_id=sub.id, portal_version_id=version_id,
        portal_document_id=expected["document_id"], document_id=doc.id, code=expected["code"],
        version=expected["version"], sha256=expected["sha256"])
    db.add(mapped)
    audit_service.record(db, audit_context(request, actor), "portal.document_mapped",
        entity_type="application", entity_id=sub.application_id,
        data={"portal_version_id": version_id, "portal_document_id": expected["document_id"],
              "document_id": doc.id, "sha256": expected["sha256"], "version": expected["version"]})
    db.commit()
    return {"document_id": doc.id, "state": "stored"}


@router.post("/submissions/{portal_id}/{version}/complete")
def complete(portal_id: str, version: int, request: Request, db: DbSession, actor: Actor) -> dict:
    sub = _submission(db, actor, portal_id, version)
    count = db.execute(select(func.count()).select_from(PortalDocument).where(PortalDocument.submission_id == sub.id)).scalar_one()
    if count != sub.expected_documents:
        raise ConflictError(f"Received {count} of {sub.expected_documents} document versions", code="documents_incomplete")
    if sub.state != "received":
        sub.state = "received"
        audit_service.record(db, audit_context(request, actor), "portal.submission_received",
            entity_type="application", entity_id=sub.application_id,
            data={"submission_id": sub.id, "portal_application_id": portal_id, "version": version})
        db.commit()
    return {"submission_id": sub.id, "application_id": sub.application_id, "state": "received"}


def _route_review(db, request: Request, actor: User, application_id: str) -> None:
    """Assign every received application and its findings to an active reviewer."""
    if not get_settings().portal_auto_assign:
        return
    unassigned = db.execute(select(ReviewItem).where(ReviewItem.application_id == application_id,
        ReviewItem.assignee_id.is_(None), ReviewItem.status == ReviewStatus.OPEN.value)).scalars().all()
    candidates = db.execute(select(User).where(User.institution_id == actor.institution_id,
        User.is_active.is_(True), User.email != actor.email)).scalars().all()
    reviewers = [u for u in candidates if u.role == Role.REVIEWER.value]
    if not reviewers:
        audit_service.record(db, audit_context(request, actor), "portal.assignment_pending",
            entity_type="application", entity_id=application_id,
            data={"reason": "no_active_reviewer", "items": len(unassigned)})
        db.commit()
        return
    loads = dict(db.execute(select(ReviewItem.assignee_id, func.count()).where(
        ReviewItem.assignee_id.in_([u.id for u in reviewers]),
        ReviewItem.status.in_([ReviewStatus.OPEN.value, ReviewStatus.AWAITING_DOCUMENT.value,
                              ReviewStatus.ESCALATED.value])).group_by(ReviewItem.assignee_id)).all())
    app = db.get(Application, application_id)
    target = next((u for u in reviewers if u.id in app.editor_ids()), None)
    if target is None:
        preferred = (get_settings().portal_reviewer_email or "").lower()
        target = next((u for u in reviewers if u.email.lower() == preferred), None)
    if target is None:
        target = min(reviewers, key=lambda u: (loads.get(u.id, 0), u.email))
    if target.id not in app.editor_ids():
        application_service.add_member(db, audit_context(request, actor), actor, application_id,
            target.email, MemberRole.CONTRIBUTOR)
    for item in unassigned:
        db.refresh(item)
        review_service.act(db, audit_context(request, actor), actor, item.id,
            review_service.ActionIn(action="assigned", expected_version=item.version, assignee_id=target.id,
                request_id=f"portal-route-{item.id}"))


@router.post("/submissions/{portal_id}/{version}/evaluate")
def evaluate(portal_id: str, version: int, request: Request, db: DbSession, actor: Actor,
             storage: Annotated[LocalStorage, Depends(get_storage)]) -> dict:
    sub = _submission(db, actor, portal_id, version)
    if sub.state != "received":
        raise ConflictError("Submission has not been fully received", code="submission_incomplete")
    if sub.validation_run_id:
        return {"state": "complete", "validation_run_id": sub.validation_run_id}
    if sub.validation_state == "no_rules" and not any(
        version.rule.category in ("aicte", "portal") for version in rule_service.active_versions(db, date.today())
    ):
        return {"state": "no_rules", "validation_run_id": None, "error": "no_rules_in_force"}
    mapped_ids = select(PortalDocument.document_id).where(PortalDocument.submission_id == sub.id)
    docs = db.execute(select(Document).where(Document.id.in_(mapped_ids))).scalars().all()
    if any(d.status in (DocumentStatus.QUEUED.value, DocumentStatus.PROCESSING.value) for d in docs):
        return {"state": "processing", "validation_run_id": None}
    failed_ids = [d.id for d in docs if d.status == DocumentStatus.FAILED.value]
    try:
        for doc in docs:
            trust_service.verify(db, audit_context(request, actor), actor, storage, sub.application_id, doc.id)
        evidence_service.analyze(db, audit_context(request, actor), actor, sub.application_id, force=False)
        run = validation_service.run(db, audit_context(request, actor), actor, sub.application_id, None,
            trigger="portal_submission", trigger_data={"submission_id": sub.id,
                "portal_application_id": portal_id, "version": version, "failed_document_ids": failed_ids},
            rule_categories=("aicte", "portal"))
    except DomainError as exc:
        db.rollback()
        sub = _submission(db, actor, portal_id, version)
        sub.validation_state = "no_rules" if exc.code == "no_rules_in_force" else "error"
        sub.validation_error = exc.code
        audit_service.record(db, audit_context(request, actor), "portal.validation_unavailable",
            entity_type="application", entity_id=sub.application_id, outcome="failure",
            data={"submission_id": sub.id, "reason": exc.code, "failed_document_ids": failed_ids})
        db.commit()
        return {"state": sub.validation_state, "validation_run_id": None, "error": exc.code}
    try:
        _route_review(db, request, actor, sub.application_id)
    except Exception as exc:  # routing failure must not duplicate the completed validation run
        db.rollback()
        audit_service.record(db, audit_context(request, actor), "portal.assignment_failed",
            entity_type="application", entity_id=sub.application_id, outcome="failure",
            data={"submission_id": sub.id, "error_type": type(exc).__name__})
        db.commit()
    sub = _submission(db, actor, portal_id, version)
    sub.validation_state = "complete"
    sub.validation_run_id = run.id
    sub.validation_error = None
    audit_service.record(db, audit_context(request, actor), "portal.validation_complete",
        entity_type="application", entity_id=sub.application_id,
        data={"submission_id": sub.id, "validation_run_id": run.id, "failed_document_ids": failed_ids})
    db.commit()
    return {"state": "complete", "validation_run_id": run.id}


@router.get("/submissions/{portal_id}/{version}")
def receipt(portal_id: str, version: int, db: DbSession, actor: Actor) -> dict:
    sub = _submission(db, actor, portal_id, version)
    app = db.get(Application, sub.application_id)
    requests = db.execute(select(ReviewItem).where(
        ReviewItem.application_id == app.id,
        ReviewItem.status == ReviewStatus.AWAITING_DOCUMENT.value,
    )).scalars().all()
    assigned = db.execute(select(ReviewItem).where(ReviewItem.application_id == app.id,
        ReviewItem.assignee_id.is_not(None)).order_by(ReviewItem.updated_at.desc())).scalars().first()
    reviewer = assigned.assignee.full_name if assigned and assigned.assignee else None
    if reviewer is None:
        members = [u for u in db.execute(select(User).where(User.id.in_(app.editor_ids()),
            User.is_active.is_(True))).scalars() if u.role == Role.REVIEWER.value and u.id != app.owner_id]
        reviewer = min(members, key=lambda u: u.email).full_name if members else None
    return {"submission_id": sub.id, "application_id": sub.application_id, "state": sub.state,
            "application_status": app.status, "reference": app.reference,
            "review_stage": app.review_stage,
            "validation_state": sub.validation_state, "validation_run_id": sub.validation_run_id,
            "validation_error": sub.validation_error,
            "assigned_reviewer": reviewer,
            "document_requests": [{"id": item.id, "description": item.document_request.get("description", "")}
                                  for item in requests if item.document_request]}
