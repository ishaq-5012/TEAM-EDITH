"""AI assistance: document classification, field suggestions and plain-language explanations of stored findings.

What AI may do here, and nothing more:
- *suggest* a document type from an allowlist (never applied automatically);
- *suggest* field values, each of which must be quoted verbatim from the page it cites and pass the field's own
  normalizer (never written to extracted fields; a person uses the existing correction workflow);
- *explain* a result VerifyFlow already computed. Every statement must cite stored records, and every citation is
  verified against the database before it is shown.

It never determines authenticity, changes rules, authorizes anyone, or changes a deterministic result: nothing it
returns is read by the rule engine, trust checks or review decisions, and the deterministic result is always shown
alongside, labelled as the authoritative one. When AI is off, unconfigured, over budget or fails, every endpoint
still answers with the deterministic fallback.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import UTC, datetime
from datetime import time as dtime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.assist import egress, guard, prompts
from app.assist.schemas import (
    CLASSIFICATION_SCHEMA,
    DOCUMENT_TYPES,
    EXPLANATION_SCHEMA,
    ClassificationOutput,
    ExplanationOutput,
    FieldSuggestionsOutput,
    field_suggestions_schema,
)
from app.core.config import Settings, get_settings
from app.core.errors import NotFoundError
from app.core.roles import Permission, has_permission
from app.extraction.definitions import load_definitions
from app.extraction.normalizers import normalize
from app.integrations.ai.base import AIEgressBlocked, AIError, AIProviderUnavailable, StructuredRequest
from app.integrations.ai.gateway import AIGateway, GatewayResult, health
from app.integrations.ai.registry import get_provider
from app.models.ai import AIInteraction, AIStatus, AITask
from app.models.application import Application, Document
from app.models.extraction import ExtractionRun
from app.models.user import User
from app.services import ai_context, application_service, audit_service, extraction_service
from app.services.application_service import ApplicationForbidden
from app.services.audit_service import AuditContext

# Replaced in tests so retries don't really sleep.
_sleep = time.sleep

LIMITATIONS = [
    "AI output is advisory. The deterministic result shown with it is the one VerifyFlow uses; AI never changes it.",
    "AI never determines whether a document is authentic, decides an application, or changes a rule.",
    "Every statement cites stored records, and each citation was checked against the database. Statements with a "
    "citation that could not be verified were removed.",
    "The model may still misread or oversimplify the records it was given. Check the linked evidence before "
    "relying on a statement.",
]

TASK_LABELS = {
    AITask.EXPLANATION: "Plain-language explanations of findings",
    AITask.CLASSIFICATION: "Document classification suggestions",
    AITask.FIELD_SUGGESTIONS: "Structured field suggestions",
}

ERROR_MESSAGES = {
    "ai_unavailable": "AI assistance is not available. The deterministic result is shown instead.",
    "ai_timeout": "The AI provider did not respond in time.",
    "ai_rate_limited": "The AI provider is rate limiting requests. Try again shortly.",
    "ai_local_rate_limit": "Too many AI requests right now. Try again in a minute.",
    "ai_user_rate_limit": "You have reached your hourly AI request limit.",
    "ai_provider_error": "The AI provider returned an error.",
    "ai_unreachable": "The AI provider could not be reached.",
    "ai_auth_failed": "The AI provider rejected the configured credentials.",
    "ai_model_unavailable": "The configured AI model is not available.",
    "ai_bad_request": "The AI provider rejected the request.",
    "ai_refused": "The model declined to answer.",
    "ai_empty_output": "The model returned no content.",
    "ai_invalid_output": "The model's answer was not valid JSON in the expected shape, so it was discarded.",
    "ai_truncated_output": "The model's answer was cut off, so it was discarded.",
    "ai_budget_exceeded": "Today's AI budget has been reached.",
    "ai_input_too_large": "The request is larger than the configured input limit.",
    "ai_egress_blocked": "The data-egress policy doesn't allow the document content this task needs to leave.",
    "ai_no_text": "This document has no extracted text to work from.",
    "ai_all_rejected": "Nothing in the model's answer passed VerifyFlow's checks, so none of it is shown.",
}


def _message(code: str | None, fallback: str = "") -> str:
    return ERROR_MESSAGES.get(code or "", fallback or "AI assistance failed.")


# ------------------------------------------------------------------ provider, budget, access


def gateway() -> AIGateway:
    return AIGateway(get_provider(), get_settings(), sleep=lambda s: _sleep(s))


def spent_today_usd(db: Session) -> float:
    start = datetime.combine(datetime.now(UTC).date(), dtime.min, tzinfo=UTC)
    total = db.execute(select(func.coalesce(func.sum(AIInteraction.cost_usd), 0.0)).where(
        AIInteraction.created_at >= start
    )).scalar_one()
    return float(total or 0.0)


def can_request(user: User, app: Application) -> bool:
    """Requesting AI spends budget and records data egress: case workers with edit access, on a live application."""
    return (
        has_permission(user.role, Permission.VALIDATION_RUN)
        and application_service.can_edit(user, app)
        and app.status != "archived"
    )


def _require_request(user: User, app: Application) -> None:
    if not can_request(user, app):
        raise ApplicationForbidden("You can view AI assistance for this application but not request it")
    application_service.ensure_mutable(app)


def provider_state() -> dict:
    s = get_settings()
    p = get_provider()
    st = p.status()
    return {
        "name": p.name,
        "configured_name": s.ai_provider,
        "enabled": st.enabled,
        "configured": st.configured,
        "model": st.model,
        "detail": st.detail,
        "health": health().as_dict(),
    }


def _task_availability(s: Settings, enabled: bool) -> list[dict]:
    out = []
    for task, needed in (
        (AITask.EXPLANATION, "none"),
        (AITask.CLASSIFICATION, "page_text"),
        (AITask.FIELD_SUGGESTIONS, "page_text"),
    ):
        if not enabled:
            available, reason = False, "AI provider is off or not configured; deterministic results are shown."
        elif not egress.allows(s.ai_document_egress, needed):
            available, reason = False, (
                f"Needs VERIFYFLOW_AI_DOCUMENT_EGRESS={needed}; the current policy is {s.ai_document_egress}."
            )
        else:
            available, reason = True, ""
        out.append({"key": task.value, "label": TASK_LABELS[task], "available": available, "reason": reason})
    return out


EGRESS_DESCRIPTIONS = {
    "none": "Only rule and finding metadata leave this environment: no extracted values, page text or file names.",
    "extracted_values": "Rule and finding metadata plus extracted and corrected field values and file names may "
    "leave this environment. No page text.",
    "page_text": "Page text from documents may leave this environment (needed for classification and field "
    "suggestions), in addition to extracted values.",
}


def status(db: Session) -> dict:
    s = get_settings()
    prov = provider_state()
    spent = spent_today_usd(db)
    return {
        "provider": prov,
        "egress": {
            "policy": s.ai_document_egress,
            "description": EGRESS_DESCRIPTIONS[s.ai_document_egress],
            "mask_identifiers": s.ai_mask_identifiers,
            "max_input_chars": s.ai_max_input_chars,
        },
        "limits": {
            "timeout_seconds": s.ai_timeout_seconds,
            "max_retries": s.ai_max_retries,
            "max_output_tokens": s.ai_max_output_tokens,
            "rate_limit_per_minute": s.ai_rate_limit_per_minute,
            "user_rate_limit_per_hour": s.ai_user_rate_limit_per_hour,
        },
        "budget": {
            "daily_usd": s.ai_daily_budget_usd,
            "spent_today_usd": round(spent, 6),
            "remaining_usd": round(max(s.ai_daily_budget_usd - spent, 0.0), 6),
            "input_usd_per_mtok": s.ai_input_usd_per_mtok,
            "output_usd_per_mtok": s.ai_output_usd_per_mtok,
        },
        "tasks": _task_availability(s, prov["enabled"]),
        "limitations": LIMITATIONS,
    }


def check(db: Session, ctx: AuditContext) -> dict:
    """Reachability and credentials check (no tokens spent). Audited."""
    ok, detail, code = True, "", None
    try:
        detail = gateway().ping()
    except AIError as exc:
        ok, detail, code = False, _message(exc.code, exc.message), exc.code
    audit_service.record(
        db, ctx, "ai.health_checked", entity_type="system", entity_id="ai",
        summary=f"AI provider check: {'reachable' if ok else code}",
        data={"ok": ok, "error_code": code, "provider": get_provider().name}, outcome="success" if ok else "failure",
    )
    db.commit()
    return {"ok": ok, "detail": detail, "error_code": code, "provider": provider_state()}


# ------------------------------------------------------------------ persistence helpers


def _fingerprint(task: str, s: Settings, request: StructuredRequest) -> str:
    material = json.dumps(
        [task, prompts.PROMPT_VERSION, s.ai_provider, s.ai_model, s.ai_document_egress, s.ai_mask_identifiers,
         request.system, request.user_content, request.json_schema],
        sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _cached(db: Session, task: str, subject_type: str, subject_id: str, fp: str) -> AIInteraction | None:
    return db.execute(
        select(AIInteraction)
        .where(
            AIInteraction.task == task,
            AIInteraction.subject_type == subject_type,
            AIInteraction.subject_id == subject_id,
            AIInteraction.input_fingerprint == fp,
            AIInteraction.status.in_([AIStatus.SUCCEEDED.value, AIStatus.PARTIAL.value]),
        )
        .order_by(AIInteraction.created_at.desc(), AIInteraction.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def _latest(db: Session, task: str, subject_type: str, subject_id: str) -> AIInteraction | None:
    return db.execute(
        select(AIInteraction)
        .where(
            AIInteraction.task == task,
            AIInteraction.subject_type == subject_type,
            AIInteraction.subject_id == subject_id,
        )
        .order_by(AIInteraction.created_at.desc(), AIInteraction.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def _call(
    db: Session,
    actx: AuditContext,
    user: User,
    *,
    app: Application,
    document_id: str | None,
    task: AITask,
    subject_type: str,
    subject_id: str,
    request: StructuredRequest,
    output_model: type[BaseModel],
    manifest: egress.Manifest,
    refresh: bool,
    validate,  # noqa: ANN001 - Callable[[BaseModel], tuple[dict, dict, str]] -> (output, validation, status)
) -> tuple[AIInteraction | None, bool, AIError | None]:
    """Run one task through the gateway, validate, persist and audit. Returns (row, cached, preflight error)."""
    s = get_settings()
    fp = _fingerprint(task.value, s, request)
    if not refresh:
        hit = _cached(db, task.value, subject_type, subject_id, fp)
        if hit is not None:
            return hit, True, None

    manifest.chars_sent = len(request.user_content)
    try:
        result: GatewayResult = gateway().call(
            request, output_model, user_id=user.id, spent_today_usd=spent_today_usd(db)
        )
    except AIError as exc:
        if not getattr(exc, "attempts", 0):
            # Refused before anything left the environment (off, unconfigured, over budget, rate limited).
            audit_service.record(
                db, actx, "ai.blocked", entity_type="application", entity_id=app.id,
                summary=f"AI {task.value} not requested: {exc.code}",
                data={"task": task.value, "subject_type": subject_type, "subject_id": subject_id,
                      "error_code": exc.code}, outcome="failure",
            )
            db.commit()
            return None, False, exc
        row = AIInteraction(
            application_id=app.id, document_id=document_id, task=task.value, subject_type=subject_type,
            subject_id=subject_id, status=AIStatus.FAILED.value, error_code=exc.code, provider=get_provider().name,
            model=s.ai_model, prompt_version=prompts.PROMPT_VERSION, input_fingerprint=fp,
            egress=manifest.as_dict(), output=None, validation={"error_message": _message(exc.code, exc.message)},
            attempts=exc.attempts, created_by_id=user.id,  # type: ignore[attr-defined]
        )
        _persist(db, actx, row, app)
        return row, False, None

    output, validation, status_value = validate(result.output)
    validation["served_by"] = result.response.served_by
    row = AIInteraction(
        application_id=app.id, document_id=document_id, task=task.value, subject_type=subject_type,
        subject_id=subject_id, status=status_value,
        error_code="ai_all_rejected" if status_value == AIStatus.REJECTED.value else None,
        provider=get_provider().name, model=result.response.model, prompt_version=prompts.PROMPT_VERSION,
        input_fingerprint=fp, egress=manifest.as_dict(),
        output=output if status_value != AIStatus.REJECTED.value else None, validation=validation,
        input_tokens=result.response.input_tokens, output_tokens=result.response.output_tokens,
        cost_usd=round(result.cost_usd, 8), attempts=result.attempts, duration_ms=result.duration_ms,
        created_by_id=user.id,
    )
    _persist(db, actx, row, app)
    return row, False, None


def _persist(db: Session, actx: AuditContext, row: AIInteraction, app: Application) -> None:
    db.add(row)
    db.flush()
    audit_service.record(
        db, actx, "ai.requested", entity_type="application", entity_id=app.id,
        summary=f"AI {row.task} for {row.subject_type.replace('_', ' ')}: {row.status}"
        + (f" ({row.error_code})" if row.error_code else ""),
        data={
            "interaction_id": row.id,
            "task": row.task,
            "subject_type": row.subject_type,
            "subject_id": row.subject_id,
            "status": row.status,
            "error_code": row.error_code,
            "provider": row.provider,
            "model": row.model,
            "input_tokens": row.input_tokens,
            "output_tokens": row.output_tokens,
            "cost_usd": row.cost_usd,
            "egress_categories": row.egress.get("categories", []),
            "chars_sent": row.egress.get("chars_sent", 0),
            "injection_signals": len(row.egress.get("injection_signals", [])),
        },
        outcome="success" if row.status in (AIStatus.SUCCEEDED.value, AIStatus.PARTIAL.value) else "failure",
    )
    db.commit()
    db.refresh(row)


def _row_out(row: AIInteraction | None, *, cached: bool, current_fp: str | None = None) -> dict | None:
    if row is None:
        return None
    error = None
    if row.error_code:
        error = {"code": row.error_code, "message": row.validation.get("error_message") or _message(row.error_code)}
    return {
        "interaction_id": row.id,
        "status": row.status,
        "error": error,
        "output": row.output,
        "validation": {k: v for k, v in row.validation.items() if k != "error_message"},
        "provider": row.provider,
        "model": row.model,
        "prompt_version": row.prompt_version,
        "created_at": row.created_at,
        "created_by": {"id": row.created_by.id, "full_name": row.created_by.full_name},
        "cached": cached,
        "stale": current_fp is not None and row.input_fingerprint != current_fp,
        "egress": row.egress,
        "usage": {
            "input_tokens": row.input_tokens,
            "output_tokens": row.output_tokens,
            "cost_usd": row.cost_usd,
            "attempts": row.attempts,
            "duration_ms": row.duration_ms,
        },
    }


def _error_out(exc: AIError | None) -> dict | None:
    return None if exc is None else {"code": exc.code, "message": _message(exc.code, exc.message)}


# ------------------------------------------------------------------ explanations


SUBJECTS = {
    "review_item": ai_context.review_item_context,
    "evidence_finding": ai_context.finding_context,
    "application": ai_context.application_context,
}


def _context(db: Session, user: User, subject_type: str, subject_id: str) -> ai_context.Context:
    builder = SUBJECTS.get(subject_type)
    if builder is None:
        raise NotFoundError("Unknown explanation subject")
    return builder(db, user, get_settings(), subject_id)


def _explanation_request(c: ai_context.Context) -> StructuredRequest:
    s = get_settings()
    # Keep whole records within the input cap; the subject's own records come first.
    kept: list[ai_context.Record] = []
    used = 0
    for r in c.records:
        size = sum(len(n) + len(str(v)) + 3 for n, v in r.lines) + 60
        if used + size > s.ai_max_input_chars and kept:
            c.manifest.truncated = True
            break
        kept.append(r)
        used += size
    c.records = kept
    for r in kept:
        for name, value in r.lines:
            c.manifest.note_signals(f"{r.ref} {name}", str(value))
    det = c.deterministic
    if c.subject_type == "application":
        header = (
            f"Subject: application {det.get('reference')} with {det.get('documents')} document(s). Deterministic "
            f"overall state: {det.get('outcome')}. Rule outcomes in the latest run: {det.get('rule_outcomes')}. "
            f"Cross-document outcomes: {det.get('evidence_outcomes')}. Summarize it using the records below.\n\n"
        )
    else:
        header = (
            f"Subject: {c.subject_type.replace('_', ' ')}. Deterministic outcome: {det.get('outcome')} "
            f"(severity {det.get('severity')}). Explain this outcome using the records below.\n\n"
        )
    return StructuredRequest(
        task=AITask.EXPLANATION.value,
        system=prompts.APPLICATION_SUMMARY if c.subject_type == "application" else prompts.EXPLANATION,
        user_content=header + c.render(),
        json_schema=EXPLANATION_SCHEMA,
        max_output_tokens=s.ai_max_output_tokens,
    )


def _resolve(c: ai_context.Context, refs: list[str]) -> list[dict]:
    by_ref = {r.ref: r for r in c.records}
    out = []
    for ref in refs:
        r = by_ref.get(ref)
        kind = (ai_context.parse_ref(ref) or ("unknown", ""))[0]
        out.append({"id": ref, "kind": kind, "label": r.label if r else ref, "link": r.link if r else None})
    return out


def _validate_explanation(db: Session, c: ai_context.Context):  # noqa: ANN202
    def validate(out: ExplanationOutput) -> tuple[dict, dict, str]:
        cited = [ref for st in out.statements for ref in st.references]
        verdicts = ai_context.verify_references(db, c.application.id, cited, c.refs)
        kept, dropped = [], []
        for i, st in enumerate(out.statements):
            reasons = []
            bad = [ref for ref in st.references if verdicts.get(ref) != "ok"]
            if bad:
                reasons.append("unverified_reference")
            reasons += guard.violations(st.text)
            if reasons:
                dropped.append({"index": i, "reasons": reasons, "references": st.references})
                continue
            kept.append({"text": st.text, "references": _resolve(c, list(dict.fromkeys(st.references)))})
        limitations, dropped_limits = [], 0
        for text in out.limitations:
            if guard.violations(text):
                dropped_limits += 1
            else:
                limitations.append(text)
        validation = {
            "statements_returned": len(out.statements),
            "statements_kept": len(kept),
            "dropped_statements": dropped,
            "dropped_limitations": dropped_limits,
            "rejected_references": [{"ref": ref, "reason": v} for ref, v in verdicts.items() if v != "ok"],
            "references_checked": len(verdicts),
        }
        if not kept:
            status_value = AIStatus.REJECTED.value
        elif dropped or dropped_limits:
            status_value = AIStatus.PARTIAL.value
        else:
            status_value = AIStatus.SUCCEEDED.value
        return {"statements": kept, "limitations": limitations}, validation, status_value

    return validate


def _explanation_payload(
    c: ai_context.Context, user: User, row: AIInteraction | None, *, cached: bool, error: AIError | None,
    current_fp: str | None,
) -> dict:
    return {
        "subject": {
            "type": c.subject_type,
            "id": c.subject_id,
            "application_id": c.application.id,
            "application_reference": c.application.reference,
        },
        "deterministic": c.deterministic,
        "fallback": {"statements": [{"text": f["text"], "references": _resolve(c, f["references"])}
                                    for f in c.fallback]},
        "ai": _row_out(row, cached=cached, current_fp=current_fp),
        "error": _error_out(error),
        "provider": provider_state(),
        "can_request": can_request(user, c.application) and get_provider().status().enabled,
        "limitations": LIMITATIONS,
    }


def explain(
    db: Session, actx: AuditContext, user: User, subject_type: str, subject_id: str, *, refresh: bool
) -> dict:
    c = _context(db, user, subject_type, subject_id)
    _require_request(user, c.application)
    request = _explanation_request(c)
    row, cached, error = _call(
        db, actx, user, app=c.application, document_id=None, task=AITask.EXPLANATION, subject_type=subject_type,
        subject_id=subject_id, request=request, output_model=ExplanationOutput, manifest=c.manifest,
        refresh=refresh, validate=_validate_explanation(db, c),
    )
    return _explanation_payload(c, user, row, cached=cached, error=error,
                                current_fp=_fingerprint(AITask.EXPLANATION.value, get_settings(), request))


def get_explanation(db: Session, user: User, subject_type: str, subject_id: str) -> dict:
    c = _context(db, user, subject_type, subject_id)
    row = _latest(db, AITask.EXPLANATION.value, subject_type, subject_id)
    fp = _fingerprint(AITask.EXPLANATION.value, get_settings(), _explanation_request(c))
    return _explanation_payload(c, user, row, cached=False, error=None, current_fp=fp)


# ------------------------------------------------------------------ document tasks


def _document(db: Session, user: User, application_id: str, document_id: str) -> tuple[Application, Document]:
    app = application_service.get_for_read(db, user, application_id)
    doc = db.get(Document, document_id)
    if doc is None or doc.application_id != app.id:
        raise NotFoundError("Document not found")
    return app, doc


def _current_run(db: Session, doc: Document) -> ExtractionRun | None:
    return db.execute(
        select(ExtractionRun).where(ExtractionRun.document_id == doc.id, ExtractionRun.is_current.is_(True))
    ).scalar_one_or_none()


def _pages_request(
    db: Session, doc: Document, task: AITask, system: str, preamble: str, schema: dict
) -> tuple[StructuredRequest, egress.Manifest, dict[int, str]]:
    """Build a page-text request, enforcing the egress policy. Raises AIEgressBlocked / AIError(ai_no_text)."""
    s = get_settings()
    if not egress.allows(s.ai_document_egress, "page_text"):
        raise AIEgressBlocked(_message("ai_egress_blocked"))
    run = _current_run(db, doc)
    pages = [(p.page_number, p.normalized_text) for p in (run.pages if run else []) if p.normalized_text.strip()]
    if not pages:
        raise AIError(_message("ai_no_text"), code="ai_no_text")
    sent, truncated = egress.pages_within(pages, s.ai_max_input_chars)
    manifest = egress.Manifest(policy=s.ai_document_egress, categories={"page_text"}, documents=[doc.id],
                               truncated=truncated)
    manifest.withheld.append("document_names")
    for number, text in sent:
        manifest.pages.append({"document_id": doc.id, "page_number": number, "chars": len(text)})
        manifest.note_signals(f"page {number}", text)
    content = preamble + "\n\n" + "\n\n".join(egress.wrap_page("Document", n, t) for n, t in sent)
    request = StructuredRequest(task=task.value, system=system, user_content=content, json_schema=schema,
                                max_output_tokens=s.ai_max_output_tokens)
    return request, manifest, dict(sent)


def _doc_subject(doc: Document) -> tuple[str, str]:
    return "document", doc.id


def classify(
    db: Session, actx: AuditContext, user: User, application_id: str, document_id: str, *, refresh: bool
) -> dict:
    app, doc = _document(db, user, application_id, document_id)
    _require_request(user, app)
    preamble = "Supported document types (choose one key):\n" + "\n".join(
        f"- {k}: {v}" for k, v in DOCUMENT_TYPES.items()
    )
    try:
        request, manifest, sent = _pages_request(
            db, doc, AITask.CLASSIFICATION, prompts.CLASSIFICATION, preamble, CLASSIFICATION_SCHEMA
        )
    except AIError as exc:
        return document_assist(db, user, application_id, document_id, errors={"classification": exc})

    def validate(out: ClassificationOutput) -> tuple[dict, dict, str]:
        pages = [p for p in dict.fromkeys(out.evidence_pages) if p in sent]
        dropped_pages = [p for p in out.evidence_pages if p not in sent]
        rationale, rationale_dropped = out.rationale, guard.violations(out.rationale)
        if rationale_dropped:
            rationale = ""
        output = {
            "document_type": out.document_type,
            "document_type_label": DOCUMENT_TYPES[out.document_type],
            "confidence": out.confidence,
            "rationale": rationale,
            "evidence_pages": pages,
            "declared_type": doc.document_type,
            "agrees_with_declared": doc.document_type == out.document_type if doc.document_type else None,
        }
        validation = {"dropped_pages": dropped_pages, "rationale_dropped": rationale_dropped}
        status_value = AIStatus.PARTIAL.value if dropped_pages or rationale_dropped else AIStatus.SUCCEEDED.value
        return output, validation, status_value

    subject_type, subject_id = _doc_subject(doc)
    row, cached, error = _call(
        db, actx, user, app=app, document_id=doc.id, task=AITask.CLASSIFICATION, subject_type=subject_type,
        subject_id=subject_id, request=request, output_model=ClassificationOutput, manifest=manifest,
        refresh=refresh, validate=validate,
    )
    return document_assist(db, user, application_id, document_id, errors={"classification": error},
                           fresh={"classification": (row, cached)})


_WS = re.compile(r"\s+")


def _squash(text: str) -> str:
    return _WS.sub(" ", text).strip()


def suggest_fields(
    db: Session, actx: AuditContext, user: User, application_id: str, document_id: str, *, refresh: bool
) -> dict:
    app, doc = _document(db, user, application_id, document_id)
    _require_request(user, app)
    s = get_settings()
    definitions, _ = load_definitions(s.field_definitions_path)
    by_key = {d.key: d for d in definitions.fields}
    preamble = "Fields to look for (key: label, type; labels documents commonly use):\n" + "\n".join(
        f"- {d.key}: {d.label}, {d.type.value}; e.g. {', '.join(d.labels[:5])}" for d in definitions.fields
    )
    try:
        request, manifest, sent = _pages_request(
            db, doc, AITask.FIELD_SUGGESTIONS, prompts.FIELD_SUGGESTIONS, preamble,
            field_suggestions_schema(list(by_key)),
        )
    except AIError as exc:
        return document_assist(db, user, application_id, document_id, errors={"field_suggestions": exc})

    run = _current_run(db, doc)
    current = {f.field_key: f for f in (run.fields if run else [])}
    corrections = extraction_service.corrections_by_key(db, doc.id)
    ocr_pages = {p.page_number for p in (run.pages if run else []) if p.text_source == "ocr"}

    def validate(out: FieldSuggestionsOutput) -> tuple[dict, dict, str]:
        kept, dropped, seen = [], [], set()
        for i, sug in enumerate(out.suggestions):
            definition = by_key.get(sug.field_key)
            page = sent.get(sug.page_number)
            reason = None
            if definition is None:
                reason = "unknown_field"
            elif page is None:
                reason = "page_not_sent"
            elif _squash(sug.quoted_text) not in _squash(page):
                reason = "quote_not_found"
            elif _squash(sug.value).casefold() not in _squash(sug.quoted_text).casefold():
                reason = "value_not_in_quote"
            norm = None
            if reason is None:
                norm = normalize(sug.value, definition, from_ocr=sug.page_number in ocr_pages)
                if norm.status == "invalid":
                    reason = "invalid_value"
            if reason is None and (sug.field_key, norm.value or sug.value) in seen:
                reason = "duplicate"
            if reason:
                dropped.append({"index": i, "field_key": sug.field_key, "reason": reason})
                continue
            seen.add((sug.field_key, norm.value or sug.value))
            field = current.get(sug.field_key)
            hist = corrections.get(sug.field_key, [])
            current_value = (
                hist[-1].normalized_value if hist else (field.normalized_value or field.raw_value if field else None)
            )
            if not current_value:
                comparison = "not_extracted"
            elif _squash(current_value).casefold() == _squash(norm.value or sug.value).casefold():
                comparison = "matches_extraction"
            else:
                comparison = "differs_from_extraction"
            kept.append({
                "field_key": sug.field_key,
                "label": definition.label,
                "value": sug.value,
                "normalized_value": norm.value,
                "normalization_status": norm.status,
                "normalization_note": norm.note,
                "page_number": sug.page_number,
                "quoted_text": sug.quoted_text,
                "comparison": comparison,
                "current_value": current_value,
                "current_field_id": field.id if field else None,
                "link": {"type": "field", "application_id": app.id, "document_id": doc.id,
                         "page_number": sug.page_number, "field_key": sug.field_key},
            })
        validation = {"suggestions_returned": len(out.suggestions), "suggestions_kept": len(kept),
                      "dropped_suggestions": dropped}
        if out.suggestions and not kept:
            status_value = AIStatus.REJECTED.value
        elif dropped:
            status_value = AIStatus.PARTIAL.value
        else:
            status_value = AIStatus.SUCCEEDED.value
        return {"suggestions": kept}, validation, status_value

    subject_type, subject_id = _doc_subject(doc)
    row, cached, error = _call(
        db, actx, user, app=app, document_id=doc.id, task=AITask.FIELD_SUGGESTIONS, subject_type=subject_type,
        subject_id=subject_id, request=request, output_model=FieldSuggestionsOutput, manifest=manifest,
        refresh=refresh, validate=validate,
    )
    return document_assist(db, user, application_id, document_id, errors={"field_suggestions": error},
                           fresh={"field_suggestions": (row, cached)})


def document_assist(
    db: Session,
    user: User,
    application_id: str,
    document_id: str,
    *,
    errors: dict[str, AIError | None] | None = None,
    fresh: dict[str, tuple[AIInteraction | None, bool]] | None = None,
) -> dict:
    """Latest classification and field suggestions for a document, with provider state and the fallback."""
    app, doc = _document(db, user, application_id, document_id)
    errors = errors or {}
    fresh = fresh or {}
    s = get_settings()
    out: dict[str, Any] = {
        "application_id": app.id,
        "document_id": doc.id,
        "document_name": doc.original_filename,
        "fallback": {
            "document_type": doc.document_type,
            "document_type_source": "declared_at_upload" if doc.document_type else None,
            "fields": "Extracted values from the deterministic extractor are in the Extraction Inspector.",
        },
        "provider": provider_state(),
        "can_request": can_request(user, app) and get_provider().status().enabled,
        "egress_allows_page_text": egress.allows(s.ai_document_egress, "page_text"),
        "tasks": _task_availability(s, get_provider().status().enabled),
        "limitations": [
            "Suggestions are never applied automatically. Use the Extraction Inspector to correct a value; the "
            "correction workflow records who changed it and why.",
            "A suggested document type is not a statement about what the document really is or whether it is "
            "genuine.",
            "Each field suggestion was checked: its quoted text appears on the cited page, the value appears in the "
            "quote, and it passes the field's normalizer. Suggestions that failed were removed.",
        ],
    }
    for key, task in (("classification", AITask.CLASSIFICATION), ("field_suggestions", AITask.FIELD_SUGGESTIONS)):
        row, cached = fresh.get(key) or (_latest(db, task.value, "document", doc.id), False)
        out[key] = _row_out(row, cached=cached)
        out[f"{key}_error"] = _error_out(errors.get(key))
    return out


__all__ = [
    "AIProviderUnavailable",
    "check",
    "classify",
    "document_assist",
    "explain",
    "get_explanation",
    "status",
    "suggest_fields",
]
