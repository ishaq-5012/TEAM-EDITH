"""Authorized CSV/JSON exports of governance data. Every export, and every refused sensitive export, is audited.

Datasets and who may export them:

| dataset              | needs                                   | contains document content                |
|----------------------|-----------------------------------------|------------------------------------------|
| metrics_summary      | exports:create                          | no (aggregates only)                     |
| review_items         | exports:create                          | no (rule, status, decision metadata)     |
| validation_results   | exports:create                          | no (outcomes; no values or traces)       |
| rule_history         | exports:create                          | no                                       |
| audit_events         | exports:create + audit:read             | no; event `data` only with sensitive     |
| extracted_fields     | exports:sensitive + explicit opt-in     | yes: extracted and corrected values      |

"Sensitive" means extracted field values (and audit event data, which can hold before/after values). It needs the
``exports:sensitive`` permission, ``include_document_values: true`` and a written reason, all recorded. Raw page
text and stored files are never exportable. Scoping is the same as the insights: only applications the user can see.
CSV cells that start with a formula character are prefixed with an apostrophe (CSV injection).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.core.roles import Permission, has_permission
from app.models.application import Application, Document
from app.models.audit import AuditEvent
from app.models.extraction import ExtractedField, ExtractionRun
from app.models.review import ReviewItem
from app.models.rules import RuleResult, ValidationRun
from app.models.user import User
from app.services import audit_service, extraction_service, insights_service
from app.services.audit_service import AuditContext
from app.services.insights_service import Scope

MAX_ROWS = 50_000
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


class ExportForbidden(DomainError):
    status_code = 403
    code = "export_forbidden"


class InvalidExport(DomainError):
    status_code = 422
    code = "invalid_export"


@dataclass(frozen=True)
class DatasetSpec:
    key: str
    label: str
    description: str
    permissions: tuple[Permission, ...]
    sensitive: bool = False


DATASETS: dict[str, DatasetSpec] = {
    s.key: s
    for s in (
        DatasetSpec("metrics_summary", "Metrics summary",
                    "Every Command Center and Insights aggregate for the selected scope and window, with definitions.",
                    (Permission.EXPORTS_CREATE,)),
        DatasetSpec("review_items", "Review items",
                    "Review items opened in the window: rule, category, outcome, severity, status, assignee and "
                    "decision. No document values.", (Permission.EXPORTS_CREATE,)),
        DatasetSpec("validation_results", "Validation results",
                    "Rule results of each application's latest validation run in the window: rule version, outcome, "
                    "severity and reason. No values or traces.", (Permission.EXPORTS_CREATE,)),
        DatasetSpec("rule_history", "Rule governance history",
                    "Rule-version lifecycle events in the window with actors and the four-eyes check.",
                    (Permission.EXPORTS_CREATE,)),
        DatasetSpec("audit_events", "Audit events",
                    "Audit events in the window with hashes. Event data (which can include before/after values) is "
                    "included only in a sensitive export.", (Permission.EXPORTS_CREATE, Permission.AUDIT_READ)),
        DatasetSpec("extracted_fields", "Extracted field values",
                    "Current extracted and corrected field values with page and quality. Contains document content.",
                    (Permission.EXPORTS_CREATE, Permission.EXPORTS_SENSITIVE), sensitive=True),
    )
}


def datasets_for(user: User) -> list[dict]:
    return [
        {
            "key": s.key,
            "label": s.label,
            "description": s.description,
            "sensitive": s.sensitive,
            "allowed": all(has_permission(user.role, p) for p in s.permissions),
            "can_include_document_values": has_permission(user.role, Permission.EXPORTS_SENSITIVE),
            "requires": [p.value for p in s.permissions],
        }
        for s in DATASETS.values()
    ]


@dataclass(frozen=True)
class ExportRequest:
    dataset: str
    format: str  # csv | json
    include_document_values: bool = False
    reason: str | None = None
    action: str | None = None  # audit_events filter
    entity_type: str | None = None  # audit_events filter


@dataclass(frozen=True)
class ExportFile:
    filename: str
    media_type: str
    content: bytes
    rows: int
    truncated: bool
    audit_seq: int


# ------------------------------------------------------------------ dataset builders (rows as flat dicts)


def _flatten(prefix: str, value: object, out: dict) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            _flatten(f"{prefix}.{k}" if prefix else str(k), v, out)
    elif isinstance(value, list):
        out[prefix] = json.dumps(value, ensure_ascii=False, default=str)
    else:
        out[prefix] = value


def _metrics(db: Session, scope: Scope) -> tuple[list[dict], dict]:
    data = insights_service.overview(db, scope)
    flat: dict = {}
    _flatten("", {"current": data["current"], "window": data["window"]}, flat)
    rows = [{"metric": k, "value": v} for k, v in sorted(flat.items())]
    return rows, {"overview": data, "definitions": insights_service.definitions()}


def _review_items(db: Session, scope: Scope) -> list[dict]:
    apps = insights_service.app_ids(scope)
    rows = db.execute(
        select(ReviewItem, Application.reference, Application.is_synthetic)
        .join(Application, Application.id == ReviewItem.application_id)
        .where(ReviewItem.application_id.in_(apps), ReviewItem.created_at >= scope.start,
               ReviewItem.created_at < scope.end)
        .order_by(ReviewItem.created_at, ReviewItem.id)
        .limit(MAX_ROWS + 1)
    ).all()
    return [
        {
            "review_item_id": it.id,
            "application_reference": ref,
            "synthetic": synthetic,
            "rule_key": it.rule_key,
            "rule_name": it.rule_name,
            "category": it.category,
            "outcome": it.outcome,
            "severity": it.severity,
            "priority": it.priority,
            "status": it.status,
            "assignee": it.assignee.email if it.assignee else None,
            "opened_at": it.created_at.isoformat(),
            "closed_at": it.closed_at.isoformat() if it.closed_at else None,
            "closed_by": it.closed_by.email if it.closed_by else None,
        }
        for it, ref, synthetic in rows
    ]


def _validation_results(db: Session, scope: Scope) -> list[dict]:
    latest = insights_service.latest_run_ids(scope, in_window=True)
    rows = db.execute(
        select(RuleResult, ValidationRun, Application.reference, Application.is_synthetic)
        .join(ValidationRun, ValidationRun.id == RuleResult.run_id)
        .join(Application, Application.id == ValidationRun.application_id)
        .where(RuleResult.run_id.in_(latest))
        .order_by(Application.reference, RuleResult.position)
        .limit(MAX_ROWS + 1)
    ).all()
    return [
        {
            "application_reference": ref,
            "synthetic": synthetic,
            "run_id": run.id,
            "run_created_at": run.created_at.isoformat(),
            "evaluation_date": run.evaluation_date.isoformat(),
            "trigger": run.trigger,
            "rule_key": r.rule_key,
            "rule_version_id": r.rule_version_id,
            "version_number": r.version_number,
            "outcome": r.outcome,
            "severity": r.severity,
            "reason": r.reason,
            "low_confidence": r.low_confidence,
        }
        for r, run, ref, synthetic in rows
    ]


def _rule_history(db: Session, scope: Scope) -> list[dict]:
    return [
        {
            "at": e["at"],
            "event": e["event"],
            "rule_key": e["rule_key"],
            "rule_name": e["rule_name"],
            "version_number": e["version_number"],
            "version_id": e["version_id"],
            "current_status": e["current_status"],
            "actor": e["actor"]["email"] if e["actor"] else None,
            "detail": e["detail"],
            "four_eyes": e["four_eyes"],
            "content_hash": e["content_hash"],
        }
        for e in insights_service.governance_events(db, scope, None)[: MAX_ROWS + 1]
    ]


def _audit_events(db: Session, scope: Scope, req: ExportRequest, with_data: bool) -> list[dict]:
    filters = [
        AuditEvent.occurred_at >= scope.start, AuditEvent.occurred_at < scope.end,
        audit_service.institution_scope(scope.user),
    ]
    if req.action:
        filters.append(AuditEvent.action.startswith(req.action) if req.action.endswith(".") else
                       AuditEvent.action == req.action)
    if req.entity_type:
        filters.append(AuditEvent.entity_type == req.entity_type)
    rows = db.execute(select(AuditEvent).where(*filters).order_by(AuditEvent.seq).limit(MAX_ROWS + 1)).scalars()
    out = []
    for e in rows:
        row = {
            "seq": e.seq,
            "occurred_at": e.occurred_at.isoformat(),
            "actor_email": e.actor_email,
            "action": e.action,
            "entity_type": e.entity_type,
            "entity_id": e.entity_id,
            "outcome": e.outcome,
            "summary": e.summary,
            "request_id": e.request_id,
            "prev_hash": e.prev_hash,
            "entry_hash": e.entry_hash,
        }
        if with_data:
            row["data"] = json.dumps(e.data, ensure_ascii=False, sort_keys=True, default=str)
        out.append(row)
    return out


def _extracted_fields(db: Session, scope: Scope) -> list[dict]:
    apps = insights_service.app_ids(scope)
    rows = db.execute(
        select(ExtractedField, Document.original_filename, Application.reference, Application.is_synthetic)
        .join(ExtractionRun, and_(ExtractionRun.id == ExtractedField.run_id, ExtractionRun.is_current.is_(True)))
        .join(Document, Document.id == ExtractedField.document_id)
        .join(Application, Application.id == Document.application_id)
        .where(Document.application_id.in_(apps))
        .order_by(Application.reference, Document.original_filename, ExtractedField.position)
        .limit(MAX_ROWS + 1)
    ).all()
    corrections: dict[str, dict] = {}
    out = []
    for f, filename, ref, synthetic in rows:
        if f.document_id not in corrections:
            corrections[f.document_id] = extraction_service.corrections_by_key(db, f.document_id)
        hist = corrections[f.document_id].get(f.field_key, [])
        out.append({
            "application_reference": ref,
            "synthetic": synthetic,
            "document": filename,
            "field_key": f.field_key,
            "status": f.status,
            "raw_value": f.raw_value,
            "normalized_value": f.normalized_value,
            "corrected_value": hist[-1].normalized_value if hist else None,
            "page_number": f.page_number,
            "method": f.method,
            "confidence": f.confidence,
            "quality_flags": json.dumps(f.quality_flags or []),
        })
    return out


# ------------------------------------------------------------------ serialization


def _cell(v: object) -> object:
    if isinstance(v, str) and v.startswith(FORMULA_PREFIXES):
        return "'" + v
    return v


def _csv(rows: list[dict]) -> bytes:
    buf = io.StringIO()
    if rows:
        fields: list[str] = []
        for r in rows:
            fields += [k for k in r if k not in fields]
        w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore", lineterminator="\r\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: _cell("" if v is None else v) for k, v in r.items()})
    # UTF-8 with BOM so spreadsheet tools detect the encoding.
    return ("﻿" + buf.getvalue()).encode("utf-8")


# ------------------------------------------------------------------ entry point


def export(db: Session, ctx: AuditContext, user: User, scope: Scope, req: ExportRequest) -> ExportFile:
    spec = DATASETS.get(req.dataset)
    if spec is None:
        raise InvalidExport(f"Unknown dataset {req.dataset!r}")
    if req.format not in ("csv", "json"):
        raise InvalidExport("format must be csv or json")
    sensitive = spec.sensitive or (req.dataset == "audit_events" and req.include_document_values)
    missing = [p.value for p in spec.permissions if not has_permission(user.role, p)]
    reason = (req.reason or "").strip()
    refusal = None
    if missing:
        refusal = f"Your role can't export {spec.label.lower()} (needs {', '.join(missing)})"
    elif sensitive and not has_permission(user.role, Permission.EXPORTS_SENSITIVE):
        refusal = "Your role can't export document values"
    elif sensitive and not req.include_document_values:
        refusal = "This export contains document values: confirm include_document_values to proceed"
    elif sensitive and len(reason) < 10:
        refusal = "Exports that contain document values need a reason of at least 10 characters"
    if refusal:
        audit_service.record(
            db, ctx, "export.denied", entity_type="export", entity_id=req.dataset, outcome="failure",
            summary=f"Refused {req.dataset} export: {refusal}",
            data={"dataset": req.dataset, "format": req.format, "sensitive": sensitive, "scope": scope.describe()},
        )
        db.commit()
        raise ExportForbidden(refusal)

    payload: dict | None = None
    if req.dataset == "metrics_summary":
        rows, payload = _metrics(db, scope)
    elif req.dataset == "review_items":
        rows = _review_items(db, scope)
    elif req.dataset == "validation_results":
        rows = _validation_results(db, scope)
    elif req.dataset == "rule_history":
        rows = _rule_history(db, scope)
    elif req.dataset == "audit_events":
        rows = _audit_events(db, scope, req, with_data=sensitive)
    else:
        rows = _extracted_fields(db, scope)
    truncated = len(rows) > MAX_ROWS
    rows = rows[:MAX_ROWS]

    generated = datetime.now(UTC)
    meta = {
        "dataset": req.dataset,
        "label": spec.label,
        "generated_at": generated.isoformat(),
        "generated_by": user.email,
        "scope": scope.describe(),
        "filters": {k: v for k, v in (("action", req.action), ("entity_type", req.entity_type)) if v},
        "rows": len(rows),
        "truncated": truncated,
        "contains_document_values": sensitive,
        "note": "Synthetic demo applications are marked in the 'synthetic' column where applicable.",
    }
    if req.format == "json":
        body = {"meta": meta, "rows": rows}
        if payload is not None:
            body["overview"] = payload["overview"]
            body["definitions"] = payload["definitions"]
        content = json.dumps(body, ensure_ascii=False, indent=2, default=str).encode("utf-8")
        media = "application/json"
    else:
        content = _csv(rows)
        media = "text/csv; charset=utf-8"
    digest = hashlib.sha256(content).hexdigest()
    event = audit_service.record(
        db, ctx, "export.created", entity_type="export", entity_id=req.dataset,
        summary=f"Exported {len(rows)} {spec.label.lower()} row(s) as {req.format.upper()}"
        + (" including document values" if sensitive else ""),
        data={**meta, "format": req.format, "sha256": digest, "bytes": len(content),
              "reason": reason if sensitive else None},
    )
    db.commit()
    stamp = generated.strftime("%Y%m%dT%H%M%SZ")
    return ExportFile(
        filename=f"verifyflow-{req.dataset}-{stamp}.{req.format}",
        media_type=media,
        content=content,
        rows=len(rows),
        truncated=truncated,
        audit_seq=event.seq,
    )
