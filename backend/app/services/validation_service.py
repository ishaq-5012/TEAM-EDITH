"""Validation runs: snapshot inputs, evaluate the rules in force, persist reproducibly, and re-verify."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import DomainError, NotFoundError
from app.core.roles import Permission, has_permission
from app.evidence import engine as evidence_engine
from app.evidence.config import load_config
from app.extraction.definitions import load_definitions
from app.models.application import Application
from app.models.evidence import EvidenceAnalysis
from app.models.rules import RuleResult, ValidationRun
from app.models.user import User
from app.rules import engine
from app.rules.schema import ENGINE_VERSION, parse_definition
from app.services import application_service, audit_service, evidence_service, rule_service
from app.services.application_service import ApplicationForbidden
from app.services.audit_service import AuditContext


def _fp(obj: object) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def build_snapshot(db: Session, app: Application, on: date) -> dict:
    """Normalized, self-contained input snapshot: everything a rule may read, with provenance."""
    definitions, _ = load_definitions()
    types = {f.key: f.type.value for f in definitions.fields}
    evidence = evidence_service.snapshot_fields(db, app, list(types))
    docs: dict[str, dict] = {}
    for e in evidence:
        doc = docs.setdefault(e.document_id, {"document_id": e.document_id, "name": e.document_name, "fields": {}})
        doc["fields"][e.field_key] = {
            "value": e.effective_value,
            "raw_value": e.raw_value,
            "normalized_value": e.normalized_value,
            "status": e.status,
            "quality": e.quality,
            "value_source": e.value_source,
            "field_type": types[e.field_key],
            "field_id": e.field_id,
            "extraction_run_id": e.extraction_run_id,
            "correction_id": e.correction_id,
            "page_number": e.page_number,
            "bbox": e.bbox,
            "method": e.method,
        }
    analysis = db.execute(
        select(EvidenceAnalysis).where(EvidenceAnalysis.application_id == app.id, EvidenceAnalysis.is_current.is_(True))
    ).scalar_one_or_none()
    ev = None
    if analysis is not None:
        config, config_hash = load_config()
        current_fp = evidence_engine.fingerprint(evidence_service.build_evidence(db, app, config), config_hash)
        ev = {
            "analysis_id": analysis.id,
            "stale": analysis.input_fingerprint != current_fp,
            "outcomes": {
                f.group_key: {"outcome": f.outcome, "finding_id": f.id, "evidence_quality": f.evidence_quality}
                for f in analysis.findings
            },
        }
    return {
        "evaluation_date": on.isoformat(),
        "application": {
            "application_id": app.id,
            "reference": app.reference,
            "application_type": app.application_type,
            "document_count": len(docs),
        },
        "documents": list(docs.values()),
        "evidence": ev,
    }


def _version_record(v) -> dict:  # noqa: ANN001
    return {
        "rule_id": v.rule_id,
        "rule_key": v.rule.key,
        "rule_name": v.rule.name,
        "version_id": v.id,
        "version_number": v.version_number,
        "content_hash": v.content_hash,
        "definition": v.definition,
        "effective_from": v.effective_from.isoformat(),
        "effective_to": v.effective_to.isoformat() if v.effective_to else None,
        "source_reference": v.source_reference,
        "owner": v.rule.owner.email,
        "approved_by": v.reviewed_by.email if v.reviewed_by else None,
        "approved_at": v.reviewed_at.isoformat() if v.reviewed_at else None,
    }


def _evaluate_all(records: list[dict], snapshot: dict) -> list[dict]:
    out = []
    for rec in records:
        definition = parse_definition(rec["definition"])
        r = engine.evaluate(definition, snapshot)
        message = (
            definition.pass_message
            if r["outcome"] == "pass"
            else (
                definition.fail_message
                if r["outcome"] in ("fail", "review") and r["reason"] == "condition_not_met"
                else ""
            )
        )
        out.append({"record": rec, "result": r, "severity": definition.severity, "message": message})
    return out


def can_run(user: User, app: Application) -> bool:
    return has_permission(user.role, Permission.VALIDATION_RUN) and application_service.can_edit(user, app)


def latest_run(db: Session, application_id: str) -> ValidationRun | None:
    return db.execute(
        select(ValidationRun)
        .where(ValidationRun.application_id == application_id)
        .order_by(ValidationRun.created_at.desc(), ValidationRun.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def run(
    db: Session,
    ctx: AuditContext,
    user: User,
    application_id: str,
    on: date | None,
    *,
    trigger: str = "manual",
    trigger_data: dict | None = None,
    rule_categories: tuple[str, ...] | None = None,
) -> ValidationRun:
    """Evaluate the rules in force, persist the run linked to the previous one, and sync the review queue."""
    app = application_service.get_for_read(db, user, application_id)
    if not can_run(user, app):
        raise ApplicationForbidden("You can view this application but not run validation")
    application_service.ensure_mutable(app)
    on = on or datetime.now(UTC).date()
    versions = rule_service.active_versions(db, on)
    if rule_categories is not None:
        versions = [version for version in versions if version.rule.category in rule_categories]
    if not versions:
        raise DomainError(
            f"No published rules are in force on {on.isoformat()}", code="no_rules_in_force", status_code=409
        )
    snapshot = build_snapshot(db, app, on)
    records = [_version_record(v) for v in versions]
    evaluated = _evaluate_all(records, snapshot)
    summary = {
        o: sum(1 for e in evaluated if e["result"]["outcome"] == o)
        for o in ("pass", "fail", "review", "insufficient", "not_applicable")
    }
    previous = latest_run(db, app.id)
    vr = ValidationRun(
        application_id=app.id,
        previous_run_id=previous.id if previous else None,
        trigger=trigger,
        trigger_data=trigger_data or {},
        evaluation_date=on,
        engine_version=ENGINE_VERSION,
        input_snapshot=snapshot,
        input_fingerprint=_fp(snapshot),
        rule_versions=records,
        ruleset_fingerprint=_fp([r["content_hash"] for r in records]),
        summary=summary,
        created_by_id=user.id,
    )
    db.add(vr)
    db.flush()
    for i, e in enumerate(evaluated):
        rec, r = e["record"], e["result"]
        db.add(
            RuleResult(
                run_id=vr.id,
                position=i,
                rule_id=rec["rule_id"],
                rule_version_id=rec["version_id"],
                rule_key=rec["rule_key"],
                rule_name=rec["rule_name"],
                version_number=rec["version_number"],
                outcome=r["outcome"],
                severity=e["severity"],
                reason=r["reason"],
                message=e["message"],
                low_confidence=r["low_confidence"],
                trace=r["trace"],
                details={k: v for k, v in r.items() if k not in ("outcome", "reason", "trace", "low_confidence")},
            )
        )
    audit_service.record(
        db,
        ctx,
        "validation.run",
        entity_type="application",
        entity_id=app.id,
        summary=f"Validation run for {app.reference} on {on.isoformat()}: "
        + ", ".join(f"{v} {k}" for k, v in summary.items() if v),
        data={
            "run_id": vr.id,
            "input_fingerprint": vr.input_fingerprint,
            "ruleset_fingerprint": vr.ruleset_fingerprint,
            "rule_versions": [r["version_id"] for r in records],
            "summary": summary,
            "previous_run_id": vr.previous_run_id,
            "trigger": trigger,
        },
    )
    db.flush()
    db.refresh(vr)
    from app.services import review_service  # local import: review_service runs validation after corrections

    review_service.sync_from_run(db, ctx, user, vr)
    db.commit()
    db.refresh(vr)
    return vr


def next_run_ids(db: Session, run_id: str) -> list[str]:
    return list(
        db.execute(
            select(ValidationRun.id).where(ValidationRun.previous_run_id == run_id).order_by(ValidationRun.created_at)
        ).scalars()
    )


def get(db: Session, user: User, application_id: str, run_id: str) -> ValidationRun:
    app = application_service.get_for_read(db, user, application_id)
    vr = db.get(ValidationRun, run_id)
    if vr is None or vr.application_id != app.id:
        raise NotFoundError("Validation run not found")
    return vr


def list_runs(db: Session, user: User, application_id: str) -> list[ValidationRun]:
    app = application_service.get_for_read(db, user, application_id)
    return list(
        db.execute(
            select(ValidationRun)
            .where(ValidationRun.application_id == app.id)
            .order_by(ValidationRun.created_at.desc())
        ).scalars()
    )


def reproduce(db: Session, user: User, application_id: str, run_id: str) -> dict:
    """Re-evaluate the stored snapshot with the stored rule definitions. Read-only."""
    vr = get(db, user, application_id, run_id)
    integrity = (
        _fp(vr.input_snapshot) == vr.input_fingerprint
        and _fp([r["content_hash"] for r in vr.rule_versions]) == vr.ruleset_fingerprint
    )
    evaluated = _evaluate_all(vr.rule_versions, vr.input_snapshot)
    differences = []
    stored_by_version = {r.rule_version_id: r for r in vr.results}
    for e in evaluated:
        rec, recomputed = e["record"], e["result"]
        stored = stored_by_version.get(rec["version_id"])
        if stored is None:
            # A stored result is missing (it should never be): report it rather than guess.
            differences.append({"rule_key": rec["rule_key"], "stored": None, "recomputed": recomputed["outcome"]})
        elif stored.outcome != recomputed["outcome"] or stored.trace != recomputed["trace"]:
            differences.append(
                {"rule_key": stored.rule_key, "stored": stored.outcome, "recomputed": recomputed["outcome"]}
            )
    return {
        "run_id": vr.id,
        "snapshot_intact": integrity,
        "identical": integrity and not differences,
        "differences": differences,
        "engine_version": ENGINE_VERSION,
        "stored_engine_version": vr.engine_version,
    }
