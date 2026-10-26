"""Trust and Authentication Center: run verifications, keep their immutable history, describe capabilities."""

from __future__ import annotations

import hashlib
import secrets
from importlib.metadata import PackageNotFoundError, version

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import DomainError, NotFoundError
from app.core.roles import Permission, has_permission
from app.models.application import Application, Document
from app.models.extraction import ExtractionRun
from app.models.trust import TrustVerification
from app.models.user import User
from app.services import application_service, audit_service, extraction_service
from app.services.application_service import ApplicationForbidden
from app.services.audit_service import AuditContext
from app.services.storage import LocalStorage
from app.trust import anchors, registries, signatures
from app.trust.checks import NOT_ESTABLISHED, Check, Dimension, State, summarize

ENGINE = "verifyflow-trust/1.0"


def _pkg(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:  # pragma: no cover - dependency is pinned in requirements
        return "unknown"


def engine_version() -> str:
    return f"{ENGINE} pyHanko/{_pkg('pyHanko')} certvalidator/{_pkg('pyhanko-certvalidator')}"


def _material() -> anchors.TrustMaterial:
    s = get_settings()
    return anchors.load(s.trust_roots_dir, s.trust_crl_dir)


def _connectors() -> list:
    s = get_settings()
    return registries.configured(
        s.registry_connectors,
        environment=s.environment,
        synthetic_path=s.registry_synthetic_path,
        http_url=s.registry_http_url,
        http_timeout=s.registry_http_timeout_seconds,
        http_name=s.registry_http_name,
    )


def capabilities() -> dict:
    """What this deployment can and can't verify, for the UI and documentation. No secrets are included."""
    s = get_settings()
    material = _material()
    connectors = _connectors()
    roots = len(material.roots)
    return {
        "engine_version": engine_version(),
        "capabilities": [
            {
                "key": "file_integrity",
                "label": "SHA-256 file integrity",
                "status": "enabled",
                "requires_external": False,
                "detail": "Re-hashes the stored file and compares it with the hash recorded at upload.",
            },
            {
                "key": "pdf_signatures",
                "label": "PDF digital signature inspection (pyHanko)",
                "status": "enabled",
                "requires_external": False,
                "detail": "Signature integrity, cryptographic validity, coverage and post-signing modifications for "
                "PDF signatures (adbe.pkcs7.detached, ETSI.CAdES.detached). Not supported: other file types, encrypted "
                "PDFs, detached or XML signatures.",
            },
            {
                "key": "certificate_trust",
                "label": "Certificate chain to configured trust anchors",
                "status": "enabled" if roots else "not_configured",
                "requires_external": True,
                "detail": f"{roots} trust anchor(s) configured."
                if roots
                else "No trust anchors configured "
                "(VERIFYFLOW_TRUST_ROOTS_DIR); signer identity is always inconclusive. "
                "The operating system's TLS trust list is never used.",
            },
            {
                "key": "revocation_offline",
                "label": "Revocation via offline CRLs",
                "status": "enabled" if material.crls else "not_configured",
                "requires_external": True,
                "detail": f"{len(material.crls)} CRL(s) loaded."
                if material.crls
                else "No CRLs configured " "(VERIFYFLOW_TRUST_CRL_DIR).",
            },
            {
                "key": "revocation_online",
                "label": "Revocation via online OCSP/CRL",
                "status": "enabled" if s.trust_revocation_fetching else "disabled",
                "requires_external": True,
                "detail": "Fetches revocation data from URLs in the certificates. Disabled by default; enable only "
                "behind an egress-allowlisting proxy.",
            },
            {
                "key": "timestamps",
                "label": "RFC 3161 timestamp validation",
                "status": "enabled" if roots else "not_configured",
                "requires_external": True,
                "detail": "Validates embedded timestamp tokens against the configured anchors. Timestamping new "
                "documents (calling a TSA) is not implemented.",
            },
            {
                "key": "registry",
                "label": "Issuer / registry verification",
                "status": "enabled" if connectors else "not_configured",
                "requires_external": True,
                "detail": ", ".join(c.name for c in connectors)
                if connectors
                else "No approved registry integration " "is configured (VERIFYFLOW_REGISTRY_CONNECTORS).",
            },
            {
                "key": "ltv",
                "label": "Long-term validation (LTV) and qualified-signature (eIDAS) status",
                "status": "not_implemented",
                "requires_external": True,
                "detail": "Validation uses the current time; archival validation with embedded DSS data and "
                "trusted-list qualification are not implemented.",
            },
        ],
        "trust_material": material.describe(),
        "registries": [{"key": c.key, "name": c.name, "requires_external": c.requires_external} for c in connectors],
        "statement": "A matching hash means the stored file is unchanged since upload, not that its issuer is "
        "authentic. A valid signature means the signed bytes are unchanged and were signed with that key, not that "
        "the document's contents are true.",
    }


# ------------------------------------------------------------------ access


def can_verify(user: User, app: Application) -> bool:
    return has_permission(user.role, Permission.VALIDATION_RUN) and application_service.can_edit(user, app)


def _document(db: Session, user: User, application_id: str, document_id: str) -> tuple[Application, Document]:
    app = application_service.get_for_read(db, user, application_id)
    doc = db.get(Document, document_id)
    if doc is None or doc.application_id != app.id:
        raise NotFoundError("Document not found")
    return app, doc


# ------------------------------------------------------------------ verification


def _integrity(storage: LocalStorage, doc: Document) -> tuple[Check, bytes | None, str | None]:
    base = {
        "dimension": Dimension.FILE_INTEGRITY,
        "key": "file_integrity",
        "label": "Stored file integrity",
        "method": "SHA-256 of the stored bytes compared with the hash recorded at upload",
        "does_not_establish": NOT_ESTABLISHED[Dimension.FILE_INTEGRITY],
    }
    try:
        data = storage.read(doc.storage_key)
    except DomainError:
        return (
            Check(
                **base,
                state=State.FAILED,
                code="file_missing",
                evidence={"recorded_sha256": doc.sha256},
                summary="The stored file is missing: the uploaded bytes can no longer be produced.",
            ),
            None,
            None,
        )
    except OSError as exc:
        return (
            Check(
                **base,
                state=State.INCONCLUSIVE,
                code="file_unavailable",
                evidence={"recorded_sha256": doc.sha256, "error": exc.__class__.__name__},
                summary="The stored file could not be read, so integrity could not be checked.",
            ),
            None,
            None,
        )
    observed = hashlib.sha256(data).hexdigest()
    ev = {"recorded_sha256": doc.sha256, "observed_sha256": observed, "size_bytes": len(data)}
    if not secrets.compare_digest(observed, doc.sha256):
        return (
            Check(
                **base,
                state=State.FAILED,
                code="hash_mismatch",
                evidence=ev,
                summary="The stored file no longer matches the hash recorded at upload: it was altered or "
                "corrupted in storage.",
            ),
            data,
            observed,
        )
    return (
        Check(
            **base,
            state=State.VERIFIED,
            code="hash_match",
            evidence=ev,
            establishes="The stored file is byte-for-byte the file that was uploaded.",
            summary="The stored file matches the SHA-256 recorded at upload.",
        ),
        data,
        observed,
    )


def _fields(db: Session, doc: Document) -> registries.Fields:
    run = db.execute(
        select(ExtractionRun).where(ExtractionRun.document_id == doc.id, ExtractionRun.is_current.is_(True))
    ).scalar_one_or_none()
    values: dict[str, str] = {}
    if run is not None:
        corrections = extraction_service.corrections_by_key(db, doc.id)
        for f in run.fields:
            hist = corrections.get(f.field_key)
            v = (
                hist[-1].normalized_value
                if hist
                else (f.normalized_value if f.status in ("found", "ambiguous") else None)
            )
            if v:
                values[f.field_key] = v
    return registries.Fields(values)


def verify(
    db: Session, ctx: AuditContext, user: User, storage: LocalStorage, application_id: str, document_id: str
) -> TrustVerification:
    app, doc = _document(db, user, application_id, document_id)
    if not can_verify(user, app):
        raise ApplicationForbidden("You can view this document but not run verification")
    application_service.ensure_mutable(app)
    s = get_settings()
    material = _material()
    integrity, data, observed = _integrity(storage, doc)
    checks: list[Check] = [integrity]
    details: list[dict] = []
    if integrity.state != State.VERIFIED:
        # Never inspect bytes that aren't the uploaded file: any result would describe the wrong document.
        checks.append(
            Check(
                dimension=Dimension.SIGNATURE_INTEGRITY,
                key="signature_integrity",
                label="Digital signature",
                state=State.INCONCLUSIVE,
                code="stored_file_not_verified",
                method=signatures.METHOD,
                does_not_establish=NOT_ESTABLISHED[Dimension.SIGNATURE_INTEGRITY],
                summary="Signatures were not inspected because the stored file is not verifiably the uploaded file.",
            )
        )
    else:
        sig_checks, details = signatures.inspect(
            data, doc.detected_mime, signatures.Options(material, s.trust_revocation_fetching)
        )
        checks += sig_checks
    fields = _fields(db, doc)
    connectors = _connectors()
    if not connectors:
        checks.append(
            Check(
                dimension=Dimension.EXTERNAL_REGISTRY,
                key="external_registry",
                label="Issuer / registry verification",
                state=State.UNSUPPORTED,
                code="no_registry_configured",
                method="None configured",
                does_not_establish=NOT_ESTABLISHED[Dimension.EXTERNAL_REGISTRY],
                summary="No approved issuer or registry integration is configured, so the document was not checked "
                "against an external source.",
            )
        )
    for c in connectors:
        checks.append(c.check(fields))
    as_dicts = [c.to_dict() for c in checks]
    record = TrustVerification(
        application_id=app.id,
        document_id=doc.id,
        recorded_sha256=doc.sha256,
        observed_sha256=observed,
        engine_version=engine_version(),
        config={
            **material.describe(),
            "revocation_fetching": s.trust_revocation_fetching,
            "registries": [{"key": c.key, "name": c.name} for c in connectors],
            "fields_used": sorted(fields.values),
        },
        checks=as_dicts,
        signatures=details,
        summary=summarize(as_dicts),
        created_by_id=user.id,
    )
    db.add(record)
    db.flush()
    audit_service.record(
        db,
        ctx,
        "trust.verified",
        entity_type="application",
        entity_id=app.id,
        summary=f"Verified “{doc.original_filename}”: "
        + ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in record.summary.items()),
        data={
            "verification_id": record.id,
            "document_id": doc.id,
            "recorded_sha256": doc.sha256,
            "observed_sha256": observed,
            "summary": record.summary,
        },
    )
    db.commit()
    db.refresh(record)
    return record


def history(db: Session, user: User, application_id: str, document_id: str) -> dict:
    app, doc = _document(db, user, application_id, document_id)
    runs = list(
        db.execute(
            select(TrustVerification)
            .where(TrustVerification.document_id == doc.id)
            .order_by(TrustVerification.created_at.desc(), TrustVerification.id.desc())
        ).scalars()
    )
    # The same file (same recorded hash) uploaded elsewhere, limited to applications this user can see.
    stmt = (
        select(Document, Application)
        .join(Application, Application.id == Document.application_id)
        .where(Document.sha256 == doc.sha256, Document.id != doc.id)
    )
    visible = application_service.visible_filter(user)
    if visible is not None:
        stmt = stmt.where(visible)
    same = [
        {"document_id": d.id, "application_id": a.id, "reference": a.reference, "filename": d.original_filename}
        for d, a in db.execute(stmt.limit(20)).all()
    ]
    return {
        "application": app,
        "document": doc,
        "verifications": runs,
        "same_hash_documents": same,
        "can_verify": can_verify(user, app) and app.status != "archived",
    }


def get(db: Session, user: User, application_id: str, document_id: str, verification_id: str) -> TrustVerification:
    _, doc = _document(db, user, application_id, document_id)
    v = db.get(TrustVerification, verification_id)
    if v is None or v.document_id != doc.id:
        raise NotFoundError("Verification not found")
    return v


def overview(db: Session, user: User, application_id: str | None, limit: int, offset: int) -> tuple[list, int]:
    """Documents visible to the user with their latest verification, newest uploads first."""
    from sqlalchemy import func

    stmt = select(Document, Application).join(Application, Application.id == Document.application_id)
    visible = application_service.visible_filter(user)
    if visible is not None:
        stmt = stmt.where(visible)
    if application_id:
        stmt = stmt.where(Document.application_id == application_id)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(Document.created_at.desc(), Document.id).limit(limit).offset(offset)).all()
    ids = [d.id for d, _ in rows]
    latest: dict[str, TrustVerification] = {}
    if ids:
        for v in db.execute(
            select(TrustVerification)
            .where(TrustVerification.document_id.in_(ids))
            .order_by(TrustVerification.created_at.asc(), TrustVerification.id.asc())
        ).scalars():
            latest[v.document_id] = v
    return [(d, a, latest.get(d.id)) for d, a in rows], total
