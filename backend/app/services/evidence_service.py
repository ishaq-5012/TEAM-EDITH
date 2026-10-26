"""Evidence analyses: build input snapshots, run the engine, persist and serve results."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import DomainError, NotFoundError
from app.core.roles import Permission, has_permission
from app.evidence import comparators, engine
from app.evidence.config import ComparisonConfig, load_config
from app.evidence.engine import FieldEvidence
from app.models.application import Application, Document
from app.models.evidence import EvidenceAnalysis, EvidenceFinding, EvidenceReference, FieldRelationship
from app.models.extraction import ExtractedField, ExtractionRun, FieldCorrection
from app.models.portal_intake import PortalSubmission
from app.models.user import User
from app.services import application_service, audit_service
from app.services.application_service import ApplicationForbidden
from app.services.audit_service import AuditContext


class NotAnalyzed(NotFoundError):
    code = "not_analyzed"


def can_analyze(user: User, app: Application) -> bool:
    return has_permission(user.role, Permission.VALIDATION_RUN) and application_service.can_edit(user, app)


def build_evidence(db: Session, app: Application, config: ComparisonConfig) -> list[FieldEvidence]:
    """Snapshot every document's current value for every compared field key, in a stable order."""
    return snapshot_fields(db, app, [k for g in config.groups for k in g.fields])


def snapshot_fields(db: Session, app: Application, keys: list[str]) -> list[FieldEvidence]:
    """Each document's current effective value (correction > extraction) for each key, in a stable order."""
    docs = (
        db.execute(select(Document).where(Document.application_id == app.id).order_by(Document.created_at, Document.id))
        .scalars()
        .all()
    )
    out: list[FieldEvidence] = []
    for doc in docs:
        run = db.execute(
            select(ExtractionRun).where(ExtractionRun.document_id == doc.id, ExtractionRun.is_current.is_(True))
        ).scalar_one_or_none()
        fields: dict[str, ExtractedField] = {}
        latest_correction: dict[str, FieldCorrection] = {}
        if run is not None:
            fields = {f.field_key: f for f in run.fields}
            for c in db.execute(
                select(FieldCorrection)
                .where(FieldCorrection.document_id == doc.id, FieldCorrection.field_key.in_(keys))
                .order_by(FieldCorrection.created_at, FieldCorrection.id)
            ).scalars():
                latest_correction[c.field_key] = c
        for key in keys:
            f = fields.get(key)
            c = latest_correction.get(key)
            if run is None:
                out.append(
                    FieldEvidence(
                        doc.id,
                        doc.original_filename,
                        None,
                        None,
                        key,
                        key,
                        "not_extracted",
                        None,
                        None,
                        None,
                        "none",
                        None,
                        None,
                        None,
                        None,
                        None,
                        (),
                    )
                )
                continue
            if f is None:  # definitions changed since extraction: the field was never looked for
                out.append(
                    FieldEvidence(
                        doc.id,
                        doc.original_filename,
                        run.id,
                        None,
                        key,
                        key,
                        "missing",
                        None,
                        None,
                        None,
                        "none",
                        None,
                        None,
                        None,
                        None,
                        None,
                        (),
                    )
                )
                continue
            effective = c.normalized_value if c else f.normalized_value
            out.append(
                FieldEvidence(
                    document_id=doc.id,
                    document_name=doc.original_filename,
                    extraction_run_id=run.id,
                    field_id=f.id,
                    field_key=key,
                    field_label=f.label,
                    status=f.status,
                    raw_value=f.raw_value,
                    normalized_value=f.normalized_value,
                    effective_value=effective,
                    value_source="correction" if c else ("extracted" if effective is not None else "none"),
                    correction_id=c.id if c else None,
                    method=f.method,
                    page_number=f.page_number,
                    bbox=list(f.bbox) if f.bbox else None,
                    confidence=f.confidence,
                    quality_flags=tuple(f.quality_flags or ()),
                )
            )
    return out


def current(db: Session, app_id: str) -> EvidenceAnalysis | None:
    return db.execute(
        select(EvidenceAnalysis).where(EvidenceAnalysis.application_id == app_id, EvidenceAnalysis.is_current.is_(True))
    ).scalar_one_or_none()


@dataclass
class AnalysisState:
    analysis: EvidenceAnalysis
    stale: bool
    current_fingerprint: str
    reused: bool = False


def _fingerprint_now(db: Session, app: Application) -> tuple[ComparisonConfig, str, list[FieldEvidence], str]:
    config, config_hash = load_config(get_settings().comparison_config_path)
    portal = db.execute(select(PortalSubmission.id).where(PortalSubmission.application_id == app.id).limit(1)).first() is not None
    scope = "portal" if portal else "general"
    config = config.model_copy(update={"groups": [group for group in config.groups if group.scope in ("all", scope)]})
    evidence = build_evidence(db, app, config)
    return config, config_hash, evidence, engine.fingerprint(evidence, config_hash)


def get_state(db: Session, user: User, application_id: str, analysis_id: str | None = None) -> AnalysisState:
    app = application_service.get_for_read(db, user, application_id)
    if analysis_id:
        analysis = db.get(EvidenceAnalysis, analysis_id)
        if analysis is None or analysis.application_id != app.id:
            raise NotFoundError("Analysis not found")
    else:
        analysis = current(db, app.id)
        if analysis is None:
            raise NotAnalyzed("No evidence analysis has been run for this application")
    _, _, _, fp = _fingerprint_now(db, app)
    return AnalysisState(analysis, stale=analysis.input_fingerprint != fp, current_fingerprint=fp)


def list_analyses(db: Session, user: User, application_id: str) -> list[EvidenceAnalysis]:
    app = application_service.get_for_read(db, user, application_id)
    return list(
        db.execute(
            select(EvidenceAnalysis)
            .where(EvidenceAnalysis.application_id == app.id)
            .order_by(EvidenceAnalysis.created_at.desc())
        ).scalars()
    )


def _persist(
    db: Session,
    app: Application,
    user: User,
    config: ComparisonConfig,
    config_hash: str,
    fp: str,
    evidence: list[FieldEvidence],
    findings: list[engine.Finding],
) -> EvidenceAnalysis:
    summary = {o: sum(1 for f in findings if f.outcome == o) for o in ("pass", "fail", "review", "insufficient")}
    summary["highest_priority"] = max((f.priority_score for f in findings), default=0)
    db.execute(
        update(EvidenceAnalysis)
        .where(EvidenceAnalysis.application_id == app.id, EvidenceAnalysis.is_current.is_(True))
        .values(is_current=False)
        .execution_options(synchronize_session=False)
    )
    analysis = EvidenceAnalysis(
        application_id=app.id,
        is_current=True,
        comparator_version=comparators.VERSION,
        config_version=config.version,
        config_hash=config_hash,
        input_fingerprint=fp,
        document_count=len({e.document_id for e in evidence}),
        summary=summary,
        created_by_id=user.id,
    )
    db.add(analysis)
    db.flush()
    for position, f in enumerate(findings):
        finding = EvidenceFinding(
            analysis_id=analysis.id,
            position=position,
            group_key=f.group_key,
            group_label=f.group_label,
            comparator=f.comparator,
            severity=f.severity,
            outcome=f.outcome,
            evidence_quality=f.evidence_quality,
            priority_score=f.priority_score,
            priority_factors=f.priority_factors,
            coverage=f.coverage,
            explanation=f.explanation,
        )
        db.add(finding)
        db.flush()
        refs: dict[tuple[str, str], EvidenceReference] = {}
        for i, e in enumerate([*f.values, *f.gaps]):
            ref = EvidenceReference(
                finding_id=finding.id,
                position=i,
                document_id=e.document_id,
                document_name=e.document_name,
                extraction_run_id=e.extraction_run_id,
                extracted_field_id=e.field_id,
                correction_id=e.correction_id,
                field_key=e.field_key,
                field_label=e.field_label,
                status=e.status,
                raw_value=e.raw_value,
                normalized_value=e.normalized_value,
                effective_value=e.effective_value,
                value_source=e.value_source,
                method=e.method,
                page_number=e.page_number,
                bbox=e.bbox,
                confidence=e.confidence,
                quality_flags=list(e.quality_flags),
                evidence_quality=e.quality,
                usable=e.usable,
            )
            db.add(ref)
            refs[(e.document_id, e.field_key)] = ref
        db.flush()
        for i, r in enumerate(f.relationships):
            db.add(
                FieldRelationship(
                    finding_id=finding.id,
                    position=i,
                    source_reference_id=refs[(r.source.document_id, r.source.field_key)].id,
                    target_reference_id=refs[(r.target.document_id, r.target.field_key)].id,
                    result=r.result,
                    method=r.method,
                    reason=r.reason,
                    details=r.details,
                    evidence_quality=r.evidence_quality,
                    explanation=r.explanation,
                )
            )
    db.flush()
    return analysis


def analyze(db: Session, ctx: AuditContext, user: User, application_id: str, *, force: bool) -> AnalysisState:
    app = application_service.get_for_read(db, user, application_id)
    if not can_analyze(user, app):
        raise ApplicationForbidden("You can view this application's evidence but not run an analysis")
    application_service.ensure_mutable(app)
    config, config_hash, evidence, fp = _fingerprint_now(db, app)
    existing = current(db, app.id)
    if existing is not None and existing.input_fingerprint == fp and not force:
        return AnalysisState(existing, stale=False, current_fingerprint=fp, reused=True)
    if not evidence:
        raise DomainError("Upload documents before running an evidence analysis", code="no_documents", status_code=409)
    findings = engine.analyze(config, evidence)
    analysis = _persist(db, app, user, config, config_hash, fp, evidence, findings)
    audit_service.record(
        db,
        ctx,
        "evidence.analyzed",
        entity_type="application",
        entity_id=app.id,
        summary=f"Evidence analysis for {app.reference}: "
        + ", ".join(f"{v} {k}" for k, v in analysis.summary.items() if k != "highest_priority"),
        data={
            "analysis_id": analysis.id,
            "input_fingerprint": fp,
            "config_hash": config_hash,
            "comparator_version": comparators.VERSION,
            "summary": analysis.summary,
            "forced": force,
        },
    )
    db.commit()
    db.refresh(analysis)
    return AnalysisState(analysis, stale=False, current_fingerprint=fp)
