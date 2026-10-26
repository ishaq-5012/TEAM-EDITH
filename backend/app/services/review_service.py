"""Review and Resolution Center.

Items are opened from validation runs (every fail / review / insufficient rule result) and updated by later
runs. People act on them through guarded, versioned actions; every action is appended to an immutable history
and to the audit chain. Nothing here modifies a rule result, a validation run or an extracted field:
corrections are appended through the extraction service, and their effect is observed by re-running validation.

Access policy (enforced here for every call, never by the UI):
- read: anyone who can read the application (owner, member, or a role with applications:read_all)
- act: review:resolve AND edit access to the application (owner, contributor, or oversight role)
- oversight decisions (anything on an escalated item; dismissing a critical failure): additionally
  applications:read_all, i.e. a compliance manager
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.core.errors import ConflictError, DomainError, NotFoundError
from app.core.roles import Permission, has_permission
from app.evidence.config import load_config
from app.models.application import Application
from app.models.extraction import DocumentPage, ExtractedField, ExtractionRun, FieldCorrection
from app.models.review import (
    ACTIVE_STATUSES,
    CATEGORY_FOR_OUTCOME,
    ReviewAction,
    ReviewActionType,
    ReviewItem,
    ReviewStatus,
)
from app.models.rules import RuleResult, ValidationRun
from app.models.user import User
from app.rules.schema import parse_definition
from app.rules.summary import definition_summary
from app.services import application_service, audit_service, extraction_service
from app.services.audit_service import AuditContext

A, S = ReviewActionType, ReviewStatus
ACTIVE = {s.value for s in ACTIVE_STATUSES}
FINDING_OUTCOMES = set(CATEGORY_FOR_OUTCOME)

SEVERITY_WEIGHT = {"critical": 40, "high": 30, "medium": 20, "low": 10}
CATEGORY_WEIGHT = {"failure": 30, "uncertain": 20, "missing": 10}


class ReviewForbidden(DomainError):
    status_code = 403
    code = "forbidden"


class StaleItem(ConflictError):
    code = "stale_item"


class InvalidReviewAction(DomainError):
    status_code = 422
    code = "invalid_review_action"


def priority_for(category: str, severity: str) -> int:
    """Queue order: severity (critical 40 … low 10) + category (failure 30, uncertain 20, missing 10)."""
    return SEVERITY_WEIGHT.get(severity, 0) + CATEGORY_WEIGHT.get(category, 0)


def _now() -> datetime:
    return datetime.now(UTC)


# ------------------------------------------------------------------ access


def _oversight(user: User) -> bool:
    return has_permission(user.role, Permission.APPLICATIONS_READ_ALL)


def can_act(user: User, app: Application) -> bool:
    return has_permission(user.role, Permission.REVIEW_RESOLVE) and application_service.can_edit(user, app)


def get_item(db: Session, user: User, item_id: str) -> tuple[ReviewItem, Application]:
    item = db.get(ReviewItem, item_id)
    if item is None:
        raise NotFoundError("Review item not found")
    try:
        app = application_service.get_for_read(db, user, item.application_id)
    except NotFoundError:
        raise NotFoundError("Review item not found") from None
    return item, app


def _require_act(user: User, app: Application) -> None:
    if not can_act(user, app):
        raise ReviewForbidden("You can view this review item but not act on it")
    application_service.ensure_mutable(app)


def _require_oversight(user: User, why: str) -> None:
    if not _oversight(user):
        raise ReviewForbidden(why, code="oversight_required")


def eligible_assignee(user: User, app: Application) -> bool:
    return user.is_active and user.institution_id == app.institution_id and can_act(user, app)


def assignees(db: Session, user: User, item_id: str) -> list[User]:
    _, app = get_item(db, user, item_id)
    users = db.execute(
        select(User).where(User.is_active.is_(True), User.institution_id == app.institution_id).order_by(User.full_name)
    ).scalars()
    return [u for u in users if eligible_assignee(u, app)]


# ------------------------------------------------------------------ history


def _append(
    db: Session,
    item: ReviewItem,
    actor: User,
    action: ReviewActionType,
    *,
    from_status: str | None = None,
    reason: str | None = None,
    data: dict | None = None,
    request_id: str | None = None,
) -> ReviewAction:
    seq = (db.execute(select(func.max(ReviewAction.sequence)).where(ReviewAction.item_id == item.id)).scalar() or 0) + 1
    entry = ReviewAction(
        item_id=item.id,
        application_id=item.application_id,
        sequence=seq,
        action=action.value,
        actor_id=actor.id,
        from_status=from_status,
        to_status=item.status,
        reason=reason,
        data=data or {},
        request_id=request_id,
    )
    db.add(entry)
    return entry


def _audit(db: Session, ctx: AuditContext, item: ReviewItem, app: Application, action: str, summary: str, data: dict):
    audit_service.record(
        db,
        ctx,
        f"review.{action}",
        entity_type="application",
        entity_id=app.id,
        summary=f"{app.reference} · {item.rule_name}: {summary}",
        data={"review_item_id": item.id, **data},
    )


# ------------------------------------------------------------------ sync from validation runs


def _evidence_key(result: RuleResult) -> str:
    """What a decision was about: the outcome and the exact values it was computed from."""
    obs = [
        (
            t.get("path"),
            t.get("result"),
            sorted((o.get("document_id") or "", str(o.get("value"))) for o in t.get("observations", [])),
        )
        for t in result.trace
    ]
    return json.dumps([result.outcome, result.reason, obs], sort_keys=True, default=str)


def _point_at(item: ReviewItem, result: RuleResult, run: ValidationRun) -> None:
    item.current_result_id = result.id
    item.current_run_id = run.id
    item.outcome = result.outcome
    item.severity = result.severity
    if result.outcome in FINDING_OUTCOMES:
        item.category = CATEGORY_FOR_OUTCOME[result.outcome].value
    item.priority = priority_for(item.category, item.severity)


def sync_from_run(db: Session, ctx: AuditContext, user: User, run: ValidationRun) -> dict[str, int]:
    """Open, update or resolve review items from a new validation run (caller commits).

    - a non-pass result with an active item: the item now points at the new result ("revalidated")
    - a non-pass result whose last item was confirmed or dismissed on identical evidence: the decision stands,
      recorded on that item, and no new item is opened
    - any other non-pass result: a new item, linked to the previous item for the same rule
    - a pass / not-applicable result with an active item: the item is resolved by revalidation
    """
    counts = {"opened": 0, "updated": 0, "resolved": 0, "decision_stands": 0}
    for result in run.results:
        items = list(
            db.execute(
                select(ReviewItem)
                .where(ReviewItem.application_id == run.application_id, ReviewItem.rule_id == result.rule_id)
                .order_by(ReviewItem.created_at.desc(), ReviewItem.id.desc())
            ).scalars()
        )
        active = next((i for i in items if i.status in ACTIVE), None)
        latest = items[0] if items else None
        if active is not None:
            prev = db.get(RuleResult, active.current_result_id)
            before = {"outcome": active.outcome, "result_id": active.current_result_id, "run_id": active.current_run_id}
            from_status = active.status
            _point_at(active, result, run)
            data = {
                "before": before,
                "after": {"outcome": result.outcome, "result_id": result.id, "run_id": run.id},
                "evidence_changed": prev is None or _evidence_key(prev) != _evidence_key(result),
                "trigger": run.trigger,
            }
            if result.outcome in FINDING_OUTCOMES:
                counts["updated"] += 1
                _append(db, active, user, A.REVALIDATED, from_status=from_status, data=data)
            else:
                active.status = S.RESOLVED.value
                active.closed_by_id, active.closed_at = user.id, _now()
                active.document_request = None
                counts["resolved"] += 1
                _append(
                    db,
                    active,
                    user,
                    A.REVALIDATED,
                    from_status=from_status,
                    reason=f"A later validation run produced “{result.outcome}”",
                    data=data,
                )
            continue
        if result.outcome not in FINDING_OUTCOMES:
            continue
        if latest is not None and latest.status in (S.CONFIRMED.value, S.DISMISSED.value):
            prev = db.get(RuleResult, latest.current_result_id)
            if prev is not None and _evidence_key(prev) == _evidence_key(result):
                before = {"result_id": latest.current_result_id, "run_id": latest.current_run_id}
                _point_at(latest, result, run)
                counts["decision_stands"] += 1
                _append(
                    db,
                    latest,
                    user,
                    A.REVALIDATED,
                    from_status=latest.status,
                    data={
                        "before": before,
                        "after": {"outcome": result.outcome, "result_id": result.id, "run_id": run.id},
                        "evidence_changed": False,
                        "decision_stands": True,
                        "trigger": run.trigger,
                    },
                )
                continue
        category = CATEGORY_FOR_OUTCOME[result.outcome].value
        item = ReviewItem(
            application_id=run.application_id,
            rule_id=result.rule_id,
            rule_key=result.rule_key,
            rule_name=result.rule_name,
            origin_result_id=result.id,
            current_result_id=result.id,
            current_run_id=run.id,
            previous_item_id=latest.id if latest else None,
            category=category,
            outcome=result.outcome,
            severity=result.severity,
            priority=priority_for(category, result.severity),
            status=S.OPEN.value,
        )
        db.add(item)
        db.flush()
        counts["opened"] += 1
        _append(
            db,
            item,
            user,
            A.OPENED,
            data={
                "run_id": run.id,
                "result_id": result.id,
                "outcome": result.outcome,
                "reason": result.reason,
                "previous_item_id": item.previous_item_id,
                "trigger": run.trigger,
            },
        )
    db.flush()
    return counts


# ------------------------------------------------------------------ actions


@dataclass
class ActionIn:
    action: str
    expected_version: int
    request_id: str | None = None
    reason: str | None = None
    assignee_id: str | None = None
    document_description: str | None = None


@dataclass
class ActionResult:
    item: ReviewItem
    action: ReviewAction
    replayed: bool = False
    revalidation: dict | None = None


def _replay(db: Session, item: ReviewItem, request_id: str | None, action: str) -> ReviewAction | None:
    if not request_id:
        return None
    existing = db.execute(
        select(ReviewAction).where(ReviewAction.item_id == item.id, ReviewAction.request_id == request_id)
    ).scalar_one_or_none()
    if existing is not None and existing.action != action:
        raise ConflictError("This request id was already used for a different action", code="request_id_reused")
    return existing


def _check_version(item: ReviewItem, expected: int) -> None:
    if item.version != expected:
        raise StaleItem(
            "Someone else updated this item since you loaded it. Review the latest state and try again.",
            details={"current_version": item.version, "status": item.status, "assignee_id": item.assignee_id},
        )


def _need_reason(reason: str | None, what: str, minimum: int = 5) -> str:
    text = (reason or "").strip()
    if len(text) < minimum:
        raise InvalidReviewAction(f"A reason of at least {minimum} characters is required to {what}")
    return text


def _require_status(item: ReviewItem, allowed: set[str], what: str) -> None:
    if item.status not in allowed:
        raise ConflictError(f"Cannot {what} an item that is {item.status.replace('_', ' ')}", code="invalid_transition")


def act(db: Session, ctx: AuditContext, user: User, item_id: str, body: ActionIn) -> ActionResult:
    item, app = get_item(db, user, item_id)
    try:
        kind = ReviewActionType(body.action)
    except ValueError:
        raise InvalidReviewAction(f"Unknown action “{body.action}”") from None
    if kind in (A.OPENED, A.REVALIDATED, A.FIELD_CORRECTED):
        raise InvalidReviewAction(f"“{kind.value}” is recorded by the system and cannot be submitted directly")
    if (prior := _replay(db, item, body.request_id, kind.value)) is not None:
        return ActionResult(item, prior, replayed=True)
    _require_act(user, app)
    _check_version(item, body.expected_version)

    from_status = item.status
    reason: str | None = (body.reason or "").strip() or None
    data: dict = {}
    summary = kind.value.replace("_", " ")

    if kind == A.COMMENTED:
        reason = _need_reason(body.reason, "add a comment", minimum=1)
    elif kind in (A.ASSIGNED, A.UNASSIGNED):
        _require_status(item, ACTIVE, "assign")
        new_id = body.assignee_id if kind == A.ASSIGNED else None
        target = None
        if kind == A.ASSIGNED:
            target = db.get(User, new_id) if new_id else None
            if target is None or not eligible_assignee(target, app):
                raise InvalidReviewAction(
                    "The assignee must be an active user who can resolve reviews on this application",
                    code="invalid_assignee",
                )
        if new_id == item.assignee_id:
            raise ConflictError("The item already has that assignee", code="no_change")
        # Taking an item away from someone else is a sensitive change and needs a reason.
        if item.assignee_id and item.assignee_id != user.id:
            reason = _need_reason(body.reason, "reassign an item held by someone else")
        data = {
            "from_assignee_id": item.assignee_id,
            "to_assignee_id": new_id,
            "from_assignee": item.assignee.full_name if item.assignee else None,
            "to_assignee": target.full_name if target else None,
        }
        item.assignee_id = new_id
        summary = f"assigned to {target.email}" if target else "unassigned"
    elif kind == A.ESCALATED:
        _require_status(item, {S.OPEN.value, S.AWAITING_DOCUMENT.value}, "escalate")
        reason = _need_reason(body.reason, "escalate")
        item.status = S.ESCALATED.value
    elif kind == A.DOCUMENT_REQUESTED:
        _require_status(item, {S.OPEN.value}, "request a document for")
        description = (body.document_description or "").strip()
        if len(description) < 5:
            raise InvalidReviewAction("Describe the document you are requesting (at least 5 characters)")
        item.document_request = {
            "description": description[:500],
            "requested_by": user.email,
            "requested_at": _now().isoformat(),
        }
        item.status = S.AWAITING_DOCUMENT.value
        data = {"document": description[:500]}
    elif kind == A.RESUMED:
        _require_status(item, {S.AWAITING_DOCUMENT.value, S.ESCALATED.value}, "resume")
        if item.status == S.ESCALATED.value:
            _require_oversight(user, "Only a compliance manager can return an escalated item")
            reason = _need_reason(body.reason, "return an escalated item")
        data = {"document_request": item.document_request}
        item.document_request = None
        item.status = S.OPEN.value
    elif kind in (A.CONFIRMED, A.DISMISSED):
        verb = "confirm" if kind == A.CONFIRMED else "dismiss"
        _require_status(item, ACTIVE, verb)
        if item.status == S.ESCALATED.value:
            _require_oversight(user, "Only a compliance manager can decide an escalated item")
        if kind == A.DISMISSED and item.outcome == "fail" and item.severity == "critical":
            _require_oversight(user, "Dismissing a critical failure requires a compliance manager")
        reason = _need_reason(body.reason, f"{verb} a finding", minimum=5 if kind == A.CONFIRMED else 10)
        item.status = S.CONFIRMED.value if kind == A.CONFIRMED else S.DISMISSED.value
        item.closed_by_id, item.closed_at = user.id, _now()
        item.document_request = None
        data = {"result_id": item.current_result_id, "run_id": item.current_run_id, "outcome": item.outcome}
    elif kind == A.REOPENED:
        _require_status(item, {S.CONFIRMED.value, S.DISMISSED.value}, "reopen")
        reason = _need_reason(body.reason, "reopen a decision")
        data = {
            "previous_decision": item.status,
            "decided_by_id": item.closed_by_id,
            "decided_at": item.closed_at.isoformat() if item.closed_at else None,
        }
        item.status = S.OPEN.value
        item.closed_by_id = item.closed_at = None
    else:  # pragma: no cover - every submittable type is handled above
        raise InvalidReviewAction("Unsupported action")

    # Every action advances the version, so a decision is always made on the latest state, comments included.
    item.updated_at = _now()
    entry = _append(db, item, user, kind, from_status=from_status, reason=reason, data=data, request_id=body.request_id)
    _audit(
        db,
        ctx,
        item,
        app,
        kind.value,
        summary,
        {"from_status": from_status, "to_status": item.status, "reason": reason, **data},
    )
    _commit(db, item, body.request_id, kind.value)
    return ActionResult(item, entry)


def _commit(db: Session, item: ReviewItem, request_id: str | None, action: str) -> None:
    item_id = item.id
    try:
        db.commit()
    except StaleDataError:
        db.rollback()
        raise StaleItem("Someone else updated this item at the same moment. Reload and try again.") from None
    except IntegrityError as exc:
        db.rollback()
        msg = str(exc.orig)
        if request_id and "request_id" in msg:
            raise ConflictError("This request was already processed", code="duplicate_request") from None
        if "uq_review_items_active_rule" in msg or "review_items.application_id" in msg:
            raise ConflictError("Another active review item exists for this rule", code="active_item_exists") from None
        if "sequence" in msg:
            raise StaleItem("Someone else updated this item at the same moment. Reload and try again.") from None
        raise
    db.expire_all()
    db.get(ReviewItem, item_id)


# ------------------------------------------------------------------ corrections + revalidation


def _rule_field_keys(definition: dict) -> tuple[set[str], set[str]]:
    """Extracted field keys and evidence group keys a rule definition reads."""
    fields, groups = set(), set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            if "field" in node:
                parts = str(node["field"]).split(".")
                if parts[0] == "extracted":
                    fields.add(parts[1])
                elif parts[0] == "evidence":
                    groups.add(parts[1])
            for k in ("all", "any"):
                for child in node.get(k, []) or []:
                    walk(child)
            if "not" in node:
                walk(node["not"])

    walk(definition.get("condition"))
    walk(definition.get("applies_when"))
    return fields, groups


def affected_rules(db: Session, field_key: str, on: date) -> list[str]:
    """Keys of rules in force on `on` whose result can change when `field_key` changes."""
    from app.services import rule_service

    config, _ = load_config()
    groups_with_field = {g.key for g in config.groups if field_key in g.fields}
    out = []
    for v in rule_service.active_versions(db, on):
        fields, groups = _rule_field_keys(v.definition)
        if field_key in fields or groups & groups_with_field:
            out.append(v.rule.key)
    return out


def correct(
    db: Session,
    ctx: AuditContext,
    user: User,
    item_id: str,
    *,
    expected_version: int,
    request_id: str | None,
    document_id: str,
    field_id: str,
    value: str,
    reason: str,
) -> ActionResult:
    """Correct an extracted field from a review item, then revalidate when the correction affects compliance."""
    from app.services import evidence_service, validation_service

    item, app = get_item(db, user, item_id)
    if (prior := _replay(db, item, request_id, A.FIELD_CORRECTED.value)) is not None:
        return ActionResult(item, prior, replayed=True)
    _require_act(user, app)
    _require_status(item, ACTIVE, "correct a field on")
    _check_version(item, expected_version)
    reason = _need_reason(reason, "correct an extracted value")

    field = db.get(ExtractedField, field_id)
    if field is None or field.document_id != document_id:
        raise NotFoundError("Field not found")
    original = {"raw_value": field.raw_value, "normalized_value": field.normalized_value, "status": field.status}
    previous = db.execute(
        select(FieldCorrection)
        .where(FieldCorrection.document_id == document_id, FieldCorrection.field_key == field.field_key)
        .order_by(FieldCorrection.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    before = previous.normalized_value if previous else (field.normalized_value or field.raw_value)
    correction = extraction_service.add_correction(
        db, ctx, user, app.id, document_id, field_id, value, reason, commit=False
    )
    run = db.get(ValidationRun, item.current_run_id)
    affected = affected_rules(db, field.field_key, run.evaluation_date)
    data = {
        "document_id": document_id,
        "field_id": field.id,
        "field_key": field.field_key,
        "field_label": field.label,
        "correction_id": correction.id,
        "original_extraction": original,
        "before": before,
        "after": correction.normalized_value,
        "affected_rules": affected,
    }
    # Bump the item version so a concurrent decision made against the pre-correction state is refused.
    item.updated_at = _now()
    entry = _append(
        db, item, user, A.FIELD_CORRECTED, from_status=item.status, reason=reason, data=data, request_id=request_id
    )
    _audit(
        db,
        ctx,
        item,
        app,
        "field_corrected",
        f"corrected {field.label}",
        {k: data[k] for k in ("field_key", "before", "after", "correction_id", "affected_rules")},
    )
    _commit(db, item, request_id, A.FIELD_CORRECTED.value)

    revalidation: dict = {"performed": False, "affected_rules": affected}
    if not affected:
        revalidation["reason"] = "No rule in force reads this field, so compliance results cannot change."
    elif not validation_service.can_run(user, app):
        revalidation["reason"] = "You are not allowed to run validation; ask someone who can to revalidate."
    else:
        try:
            if evidence_service.current(db, app.id) is not None and evidence_service.can_analyze(user, app):
                evidence_service.analyze(db, ctx, user, app.id, force=False)
            new_run = validation_service.run(
                db,
                ctx,
                user,
                app.id,
                run.evaluation_date,
                trigger="correction",
                trigger_data={"review_item_id": item.id, "correction_id": correction.id, "action_id": entry.id},
            )
            revalidation.update(
                performed=True, run_id=new_run.id, previous_run_id=new_run.previous_run_id, summary=new_run.summary
            )
        except DomainError as exc:
            db.rollback()
            revalidation["reason"] = f"Revalidation did not run: {exc.message}"
    db.expire_all()
    item = db.get(ReviewItem, item_id)
    entry = db.get(ReviewAction, entry.id)
    return ActionResult(item, entry, revalidation=revalidation)


# ------------------------------------------------------------------ queue


@dataclass
class QueueFilters:
    status: str = "active"  # active | closed | all | <status>
    category: str | None = None
    assignee: str | None = None  # me | unassigned | <user id>
    severity: str | None = None
    application_id: str | None = None
    q: str | None = None
    limit: int = 50
    offset: int = 0


def list_items(db: Session, user: User, f: QueueFilters) -> tuple[list[tuple[ReviewItem, Application]], int, dict]:
    stmt = select(ReviewItem, Application).join(Application, Application.id == ReviewItem.application_id)
    visible = application_service.visible_filter(user)
    if visible is not None:
        stmt = stmt.where(visible)
    if f.application_id:
        stmt = stmt.where(ReviewItem.application_id == f.application_id)
    counts_base = stmt
    if f.status == "active":
        stmt = stmt.where(ReviewItem.status.in_(ACTIVE))
    elif f.status == "closed":
        stmt = stmt.where(ReviewItem.status.not_in(ACTIVE))
    elif f.status != "all":
        stmt = stmt.where(ReviewItem.status == f.status)
    if f.category:
        stmt = stmt.where(ReviewItem.category == f.category)
    if f.severity:
        stmt = stmt.where(ReviewItem.severity == f.severity)
    if f.assignee == "me":
        stmt = stmt.where(ReviewItem.assignee_id == user.id)
    elif f.assignee == "unassigned":
        stmt = stmt.where(ReviewItem.assignee_id.is_(None))
    elif f.assignee:
        stmt = stmt.where(ReviewItem.assignee_id == f.assignee)
    if f.q:
        term = f.q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{term}%"
        stmt = stmt.where(
            or_(
                ReviewItem.rule_name.ilike(like, escape="\\"),
                Application.reference.ilike(like, escape="\\"),
                Application.title.ilike(like, escape="\\"),
            )
        )
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(
        stmt.order_by(ReviewItem.priority.desc(), ReviewItem.created_at.asc(), ReviewItem.id)
        .limit(f.limit)
        .offset(f.offset)
    ).all()
    sub = counts_base.subquery()
    status_counts = dict(db.execute(select(sub.c.status, func.count()).group_by(sub.c.status)).all())
    active_sub = counts_base.where(ReviewItem.status.in_(ACTIVE)).subquery()
    category_counts = dict(
        db.execute(select(active_sub.c.category, func.count()).group_by(active_sub.c.category)).all()
    )
    mine = db.execute(
        select(func.count()).select_from(
            counts_base.where(ReviewItem.status.in_(ACTIVE), ReviewItem.assignee_id == user.id).subquery()
        )
    ).scalar_one()
    return [(r[0], r[1]) for r in rows], total, {"status": status_counts, "category": category_counts, "mine": mine}


# ------------------------------------------------------------------ detail


def _uncertainty(result: RuleResult, fields: dict[str, ExtractedField], labels: dict[str, str]) -> list[dict]:
    out: list[dict] = []
    if result.reason == "missing_data":
        for ref in result.details.get("missing_fields", []):
            out.append(
                {
                    "code": "missing_data",
                    "field": ref,
                    "message": f"No usable value for {labels.get(ref, ref)} in any document.",
                }
            )
    for t in result.trace:
        for o in t.get("observations", []):
            if o.get("quality") != "low":
                continue
            if o.get("kind") == "evidence":
                why = "the evidence analysis was stale" if o.get("stale") else "the evidence finding is low quality"
                out.append(
                    {
                        "code": "low_quality_evidence",
                        "field": t["field"],
                        "message": f"{labels.get(t['field'], t['field'])}: {why}.",
                    }
                )
            else:
                f = fields.get(o.get("field_id") or "")
                flags = ", ".join(f.quality_flags) if f is not None and f.quality_flags else "low extraction quality"
                out.append(
                    {
                        "code": "low_quality_value",
                        "field": t["field"],
                        "document_id": o.get("document_id"),
                        "message": f"{o.get('document_name')}: “{o.get('value')}” is low quality ({flags}).",
                    }
                )
    if result.outcome == "review" and result.reason == "condition_not_met":
        out.append({"code": "routed_to_review", "message": "The rule routes violations to human review."})
    if result.outcome == "fail" and result.reason == "condition_not_met":
        failing = [o for t in result.trace for o in t.get("observations", []) if o.get("satisfied") is False]
        for o in failing:
            out.append(
                {
                    "code": "condition_not_met",
                    "document_id": o.get("document_id"),
                    "message": f"{o.get('document_name') or 'Application'}: “{o.get('value')}” "
                    "does not satisfy the rule.",
                }
            )
    if result.details.get("would_have_been"):
        out.append(
            {
                "code": "would_have_been",
                "message": f"With confident inputs the outcome would have been “{result.details['would_have_been']}”.",
            }
        )
    return out


def detail(db: Session, user: User, item_id: str) -> dict:
    from app.rules.schema import field_catalog
    from app.services import evidence_service

    item, app = get_item(db, user, item_id)
    result = db.get(RuleResult, item.current_result_id)
    run = db.get(ValidationRun, item.current_run_id)
    record = next((r for r in run.rule_versions if r["version_id"] == result.rule_version_id), None)
    catalog = field_catalog()
    labels = {ref: spec["label"] for ref, spec in catalog.items()}

    # Every current-run extracted field the rule reads, across the application's documents.
    keys, groups = _rule_field_keys(record["definition"] if record else {})
    config, _ = load_config()
    keys |= {k for g in config.groups if g.key in groups for k in g.fields}
    trace_ids = {o.get("field_id") for t in result.trace for o in t.get("observations", []) if o.get("field_id")}
    docs = {d.id: d for d in app_documents(db, app)}
    current_runs = {
        r.document_id: r
        for r in db.execute(
            select(ExtractionRun).where(ExtractionRun.document_id.in_(list(docs)), ExtractionRun.is_current.is_(True))
        ).scalars()
    }
    field_rows: list[ExtractedField] = []
    for doc_id in docs:
        r = current_runs.get(doc_id)
        if r is not None:
            field_rows += [f for f in r.fields if f.field_key in keys]
    seen = {f.id for f in field_rows}
    field_rows += [f for f in (db.get(ExtractedField, fid) for fid in trace_ids - seen) if f is not None]
    fields_by_id = {f.id: f for f in field_rows}
    corrections = extraction_service.corrections_by_key  # per document
    observed = {o.get("field_id"): o for t in result.trace for o in t.get("observations", []) if o.get("field_id")}
    field_out = []
    for f in field_rows:
        history = corrections(db, f.document_id).get(f.field_key, [])
        page = None
        if f.page_number:
            page = db.execute(
                select(DocumentPage).where(DocumentPage.run_id == f.run_id, DocumentPage.page_number == f.page_number)
            ).scalar_one_or_none()
        doc_run = current_runs.get(f.document_id)
        field_out.append(
            {
                "field_id": f.id,
                "document_id": f.document_id,
                "document_name": docs[f.document_id].original_filename if f.document_id in docs else "",
                "field_key": f.field_key,
                "label": f.label,
                "field_type": f.field_type,
                "status": f.status,
                "raw_value": f.raw_value,
                "normalized_value": f.normalized_value,
                "method": f.method,
                "confidence": f.confidence,
                "quality_flags": list(f.quality_flags or []),
                "page_number": f.page_number,
                "bbox": f.bbox,
                "page_width": page.width if page else None,
                "page_height": page.height if page else None,
                "is_current_extraction": doc_run is not None and doc_run.id == f.run_id,
                "in_trace": f.id in observed,
                "value_at_validation": observed.get(f.id, {}).get("value"),
                "effective_value": history[-1].normalized_value if history else (f.normalized_value or f.raw_value),
                "corrections": [
                    {
                        "id": c.id,
                        "value": c.value,
                        "normalized_value": c.normalized_value,
                        "based_on_value": c.based_on_value,
                        "reason": c.reason,
                        "actor": {"id": c.actor.id, "full_name": c.actor.full_name, "email": c.actor.email},
                        "created_at": c.created_at,
                    }
                    for c in history
                ],
            }
        )

    analysis = evidence_service.current(db, app.id)
    relevant_groups = {g.key for g in config.groups if set(g.fields) & keys} | groups
    findings = [f for f in analysis.findings if f.group_key in relevant_groups] if analysis else []

    chain = []
    prev_id = item.previous_item_id
    while prev_id and len(chain) < 20:
        prev = db.get(ReviewItem, prev_id)
        if prev is None:
            break
        chain.append(prev)
        prev_id = prev.previous_item_id

    rule_runs = db.execute(
        select(ValidationRun, RuleResult)
        .join(RuleResult, RuleResult.run_id == ValidationRun.id)
        .where(ValidationRun.application_id == app.id, RuleResult.rule_id == item.rule_id)
        .order_by(ValidationRun.created_at.desc())
        .limit(20)
    ).all()

    oversight = _oversight(user)
    acting = can_act(user, app) and app.status != "archived"
    return {
        "item": item,
        "application": app,
        "result": result,
        "run": run,
        "rule": {
            **(record or {}),
            "summary": definition_summary(parse_definition(record["definition"])) if record else None,
        },
        "uncertainty": _uncertainty(result, fields_by_id, labels),
        "fields": field_out,
        "evidence": {"analysis_id": analysis.id if analysis else None, "findings": findings},
        "history": item.actions,
        "previous_items": chain,
        "rule_runs": [
            {
                "run_id": r.id,
                "created_at": r.created_at,
                "evaluation_date": r.evaluation_date,
                "trigger": r.trigger,
                "previous_run_id": r.previous_run_id,
                "outcome": res.outcome,
                "result_id": res.id,
                "version_number": res.version_number,
            }
            for r, res in rule_runs
        ],
        "permissions": {
            "can_act": acting,
            "can_correct": acting and item.status in ACTIVE,
            "oversight": oversight,
            "can_decide": acting and item.status in ACTIVE and (item.status != S.ESCALATED.value or oversight),
        },
    }


def app_documents(db: Session, app: Application) -> list:
    from app.models.application import Document

    return list(db.execute(select(Document).where(Document.application_id == app.id)).scalars())
