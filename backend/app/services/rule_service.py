"""Rules: definitions, immutable versions, lifecycle with four-eyes approval, tests, comparison, simulation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, DomainError, NotFoundError
from app.core.roles import Permission, has_permission
from app.db.base import utcnow
from app.models.application import Application
from app.models.rules import Rule, RuleTestCase, RuleVersion, VersionStatus
from app.models.user import User
from app.rules import engine
from app.rules.cases import SyntheticCase
from app.rules.schema import ENGINE_VERSION, RuleDefinition, parse_definition
from app.rules.summary import definition_summary, diff
from app.services import audit_service
from app.services.audit_service import AuditContext

S = VersionStatus
DISCLAIMER = (
    "Outcomes are produced by configured rules applied to extracted evidence. A passing rule is not a legal or "
    "regulatory determination; rules reflect their documented source and owner, and require human judgement."
)


class InvalidRule(DomainError):
    status_code = 422
    code = "invalid_rule"


class RuleForbidden(DomainError):
    status_code = 403
    code = "forbidden"


# ------------------------------------------------------------------ helpers


def validate_definition(data: dict) -> RuleDefinition:
    try:
        return parse_definition(data)
    except ValidationError as exc:
        details = [
            {"loc": ".".join(map(str, e["loc"])), "msg": e["msg"].removeprefix("Value error, ")} for e in exc.errors()
        ]
        raise InvalidRule("The rule definition is not valid", details=details) from None


def canonical_definition(d: RuleDefinition) -> dict:
    return d.model_dump(mode="json", by_alias=True, exclude_none=True)


def content_hash(definition: dict, effective_from: date, effective_to: date | None, source: str, summary: str) -> str:
    material = {
        "definition": definition,
        "effective_from": effective_from.isoformat(),
        "effective_to": effective_to.isoformat() if effective_to else None,
        "source_reference": source,
        "change_summary": summary,
        "engine": ENGINE_VERSION,
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _require(user: User, permission: Permission) -> None:
    if not has_permission(user.role, permission):
        raise RuleForbidden("You do not have permission to perform this action")


def _window(effective_from: date, effective_to: date | None) -> None:
    if effective_to is not None and effective_to <= effective_from:
        raise InvalidRule("effective_to must be after effective_from (it is exclusive)")


def get_rule(db: Session, rule_id: str) -> Rule:
    rule = db.get(Rule, rule_id)
    if rule is None:
        raise NotFoundError("Rule not found")
    return rule


def get_version(db: Session, rule_id: str, version_id: str) -> RuleVersion:
    v = db.get(RuleVersion, version_id)
    if v is None or v.rule_id != rule_id:
        raise NotFoundError("Rule version not found")
    return v


# ------------------------------------------------------------------ create / edit


def create_rule(
    db: Session,
    ctx: AuditContext,
    user: User,
    *,
    key: str,
    name: str,
    description: str,
    category: str,
    owner_id: str | None,
    definition: dict,
    effective_from: date,
    effective_to: date | None,
    source_reference: str,
    change_summary: str,
) -> Rule:
    _require(user, Permission.RULES_MANAGE)
    parsed = validate_definition(definition)
    _window(effective_from, effective_to)
    if db.execute(select(Rule.id).where(Rule.key == key)).first():
        raise ConflictError("A rule with this key already exists", code="duplicate_rule_key")
    owner = db.get(User, owner_id) if owner_id else user
    if owner is None or not owner.is_active or not has_permission(owner.role, Permission.RULES_MANAGE):
        raise DomainError("The owner must be an active user who can manage rules", code="invalid_owner")
    rule = Rule(
        key=key,
        name=name.strip(),
        description=description.strip(),
        category=category.strip(),
        owner_id=owner.id,
        created_by_id=user.id,
    )
    db.add(rule)
    db.flush()
    canon = canonical_definition(parsed)
    db.add(
        RuleVersion(
            rule_id=rule.id,
            version_number=1,
            status=S.DRAFT.value,
            definition=canon,
            content_hash=content_hash(canon, effective_from, effective_to, source_reference, change_summary),
            effective_from=effective_from,
            effective_to=effective_to,
            source_reference=source_reference.strip(),
            change_summary=change_summary.strip(),
            created_by_id=user.id,
        )
    )
    audit_service.record(
        db,
        ctx,
        "rule.created",
        entity_type="rule",
        entity_id=rule.id,
        summary=f"Created rule {key} (draft v1)",
        data={"key": key, "owner_id": owner.id},
    )
    db.commit()
    db.refresh(rule)
    return rule


def update_rule_metadata(db: Session, ctx: AuditContext, user: User, rule_id: str, changes: dict) -> Rule:
    _require(user, Permission.RULES_MANAGE)
    rule = get_rule(db, rule_id)
    before, after = {}, {}
    if "owner_id" in changes and changes["owner_id"] is not None:
        owner = db.get(User, changes["owner_id"])
        if owner is None or not owner.is_active or not has_permission(owner.role, Permission.RULES_MANAGE):
            raise DomainError("The owner must be an active user who can manage rules", code="invalid_owner")
    for k, v in changes.items():
        if v is not None and getattr(rule, k) != v:
            before[k], after[k] = getattr(rule, k), v
            setattr(rule, k, v)
    if not after:
        raise DomainError("No changes supplied", code="no_changes")
    audit_service.record(
        db,
        ctx,
        "rule.metadata_updated",
        entity_type="rule",
        entity_id=rule.id,
        summary=f"Updated rule {rule.key}",
        data={"before": before, "after": after},
    )
    db.commit()
    return rule


def update_draft(
    db: Session, ctx: AuditContext, user: User, rule_id: str, version_id: str, changes: dict
) -> RuleVersion:
    _require(user, Permission.RULES_MANAGE)
    v = get_version(db, rule_id, version_id)
    if v.status != S.DRAFT.value:
        raise ConflictError("Only draft versions can be edited; submitted versions are immutable", code="immutable")
    if changes.get("definition") is not None:
        v.definition = canonical_definition(validate_definition(changes["definition"]))
    for k in ("effective_from", "effective_to", "source_reference", "change_summary"):
        if k in changes and (changes[k] is not None or k == "effective_to"):
            setattr(v, k, changes[k].strip() if isinstance(changes[k], str) else changes[k])
    _window(v.effective_from, v.effective_to)
    v.content_hash = content_hash(v.definition, v.effective_from, v.effective_to, v.source_reference, v.change_summary)
    audit_service.record(
        db,
        ctx,
        "rule.draft_updated",
        entity_type="rule",
        entity_id=rule_id,
        summary=f"Edited draft v{v.version_number} of {v.rule.key}",
        data={"version_id": v.id, "content_hash": v.content_hash, "fields": sorted(changes)},
    )
    db.commit()
    return v


def new_version(db: Session, ctx: AuditContext, user: User, rule_id: str, from_version_id: str | None) -> RuleVersion:
    _require(user, Permission.RULES_MANAGE)
    rule = get_rule(db, rule_id)
    if any(v.status == S.DRAFT.value for v in rule.versions):
        raise ConflictError("This rule already has an open draft", code="draft_exists")
    base = get_version(db, rule_id, from_version_id) if from_version_id else rule.versions[-1]
    v = RuleVersion(
        rule_id=rule.id,
        version_number=max(x.version_number for x in rule.versions) + 1,
        status=S.DRAFT.value,
        definition=base.definition,
        effective_from=base.effective_from,
        effective_to=base.effective_to,
        source_reference=base.source_reference,
        change_summary="",
        created_by_id=user.id,
        content_hash=content_hash(base.definition, base.effective_from, base.effective_to, base.source_reference, ""),
    )
    db.add(v)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ConflictError("This rule already has an open draft", code="draft_exists") from None
    audit_service.record(
        db,
        ctx,
        "rule.version_created",
        entity_type="rule",
        entity_id=rule.id,
        summary=f"Created draft v{v.version_number} of {rule.key} from v{base.version_number}",
        data={"version_id": v.id, "from_version_id": base.id},
    )
    db.commit()
    return v


# ------------------------------------------------------------------ tests


def add_test_case(
    db: Session,
    ctx: AuditContext,
    user: User,
    rule_id: str,
    *,
    name: str,
    description: str,
    case: dict,
    expected_outcome: str,
) -> RuleTestCase:
    _require(user, Permission.RULES_MANAGE)
    rule = get_rule(db, rule_id)
    try:
        parsed = SyntheticCase.model_validate(case)
    except ValidationError as exc:
        details = [
            {"loc": ".".join(map(str, e["loc"])), "msg": e["msg"].removeprefix("Value error, ")} for e in exc.errors()
        ]
        raise DomainError(
            "The test case is not valid", code="invalid_test_case", status_code=422, details=details
        ) from None
    tc = RuleTestCase(
        rule_id=rule.id,
        name=name.strip(),
        description=description.strip(),
        case=parsed.model_dump(mode="json"),
        expected_outcome=expected_outcome,
        created_by_id=user.id,
    )
    db.add(tc)
    db.flush()
    audit_service.record(
        db,
        ctx,
        "rule.test_case_added",
        entity_type="rule",
        entity_id=rule.id,
        summary=f"Added synthetic test case “{tc.name}” to {rule.key}",
        data={"test_case_id": tc.id},
    )
    db.commit()
    return tc


def delete_test_case(db: Session, ctx: AuditContext, user: User, rule_id: str, case_id: str) -> None:
    _require(user, Permission.RULES_MANAGE)
    tc = db.get(RuleTestCase, case_id)
    if tc is None or tc.rule_id != rule_id:
        raise NotFoundError("Test case not found")
    db.delete(tc)
    audit_service.record(
        db,
        ctx,
        "rule.test_case_deleted",
        entity_type="rule",
        entity_id=rule_id,
        summary=f"Deleted synthetic test case “{tc.name}”",
        data={"test_case_id": case_id},
    )
    db.commit()


def run_tests(definition: RuleDefinition, cases: list[RuleTestCase]) -> dict:
    results = []
    for tc in cases:
        snap = SyntheticCase.model_validate(tc.case).to_snapshot()
        r = engine.evaluate(definition, snap)
        results.append(
            {
                "test_case_id": tc.id,
                "name": tc.name,
                "expected": tc.expected_outcome,
                "actual": r["outcome"],
                "passed": r["outcome"] == tc.expected_outcome,
                "reason": r["reason"],
                "trace": r["trace"],
            }
        )
    return {
        "total": len(results),
        "passed": sum(r["passed"] for r in results),
        "failed": sum(not r["passed"] for r in results),
        "results": results,
    }


def test_cases(db: Session, rule_id: str) -> list[RuleTestCase]:
    return list(
        db.execute(
            select(RuleTestCase).where(RuleTestCase.rule_id == rule_id).order_by(RuleTestCase.created_at)
        ).scalars()
    )


# ------------------------------------------------------------------ lifecycle


def submit(db: Session, ctx: AuditContext, user: User, rule_id: str, version_id: str) -> RuleVersion:
    _require(user, Permission.RULES_MANAGE)
    v = get_version(db, rule_id, version_id)
    if v.status != S.DRAFT.value:
        raise ConflictError("Only drafts can be submitted", code="invalid_transition")
    if not v.source_reference.strip():
        raise InvalidRule(
            "Document the rule's source (policy, regulation clause or internal standard) before submitting"
        )
    if not v.change_summary.strip():
        raise InvalidRule("Describe what this version changes before submitting")
    report = run_tests(validate_definition(v.definition), test_cases(db, rule_id))
    if report["failed"]:
        raise DomainError(
            f"{report['failed']} synthetic test case(s) fail against this version",
            code="tests_failing",
            status_code=409,
            details=[
                {"name": r["name"], "expected": r["expected"], "actual": r["actual"]}
                for r in report["results"]
                if not r["passed"]
            ],
        )
    v.status = S.PENDING_APPROVAL.value
    v.submitted_by_id, v.submitted_at = user.id, utcnow()
    v.test_summary = {k: report[k] for k in ("total", "passed", "failed")}
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ConflictError(
            "Another version of this rule is already awaiting approval", code="pending_exists"
        ) from None
    audit_service.record(
        db,
        ctx,
        "rule.submitted",
        entity_type="rule",
        entity_id=rule_id,
        summary=f"Submitted {v.rule.key} v{v.version_number} for approval",
        data={"version_id": v.id, "content_hash": v.content_hash, "tests": v.test_summary},
    )
    db.commit()
    return v


def _review_guard(db: Session, user: User, rule_id: str, version_id: str) -> RuleVersion:
    _require(user, Permission.RULES_PUBLISH)
    v = get_version(db, rule_id, version_id)
    if v.status != S.PENDING_APPROVAL.value:
        raise ConflictError("Only versions awaiting approval can be reviewed", code="invalid_transition")
    if user.id in (v.created_by_id, v.submitted_by_id):
        raise RuleForbidden(
            "Four-eyes rule: the author or submitter of a version cannot approve or reject it",
            code="four_eyes_required",
        )
    return v


def approve(db: Session, ctx: AuditContext, user: User, rule_id: str, version_id: str, note: str) -> RuleVersion:
    v = _review_guard(db, user, rule_id, version_id)
    clash = next(
        (o for o in v.rule.versions if o.status == S.PUBLISHED.value and o.effective_from == v.effective_from), None
    )
    if clash:
        raise ConflictError(
            f"Published v{clash.version_number} already takes effect on {v.effective_from}; "
            "choose a different effective date or retire it first",
            code="effective_date_clash",
        )
    v.status, v.reviewed_by_id, v.reviewed_at, v.review_note = S.PUBLISHED.value, user.id, utcnow(), note.strip()
    audit_service.record(
        db,
        ctx,
        "rule.published",
        entity_type="rule",
        entity_id=rule_id,
        summary=f"Published {v.rule.key} v{v.version_number} effective {v.effective_from}",
        data={
            "version_id": v.id,
            "content_hash": v.content_hash,
            "note": note,
            "effective_from": v.effective_from.isoformat(),
            "effective_to": v.effective_to.isoformat() if v.effective_to else None,
        },
    )
    db.commit()
    return v


def reject(db: Session, ctx: AuditContext, user: User, rule_id: str, version_id: str, note: str) -> RuleVersion:
    v = _review_guard(db, user, rule_id, version_id)
    v.status, v.reviewed_by_id, v.reviewed_at, v.review_note = S.REJECTED.value, user.id, utcnow(), note.strip()
    audit_service.record(
        db,
        ctx,
        "rule.rejected",
        entity_type="rule",
        entity_id=rule_id,
        summary=f"Rejected {v.rule.key} v{v.version_number}",
        data={"version_id": v.id, "note": note},
    )
    db.commit()
    return v


def retire(db: Session, ctx: AuditContext, user: User, rule_id: str, version_id: str, reason: str) -> RuleVersion:
    _require(user, Permission.RULES_PUBLISH)
    v = get_version(db, rule_id, version_id)
    if v.status != S.PUBLISHED.value:
        raise ConflictError("Only published versions can be retired", code="invalid_transition")
    v.status, v.retired_by_id, v.retired_at, v.retire_reason = S.RETIRED.value, user.id, utcnow(), reason.strip()
    audit_service.record(
        db,
        ctx,
        "rule.retired",
        entity_type="rule",
        entity_id=rule_id,
        summary=f"Retired {v.rule.key} v{v.version_number}",
        data={"version_id": v.id, "reason": reason},
    )
    db.commit()
    return v


# ------------------------------------------------------------------ selection, comparison


def effective_on(versions: list[RuleVersion], on: date) -> RuleVersion | None:
    """The published version in force on `on`: latest effective_from <= on, whose window still covers `on`."""
    candidates = [v for v in versions if v.status == S.PUBLISHED.value and v.effective_from <= on]
    candidates.sort(key=lambda v: (v.effective_from, v.version_number), reverse=True)
    for v in candidates:
        if v.effective_to is None or on < v.effective_to:
            return v
        return None  # the newest started version has ended: nothing in force (older ones are superseded)
    return None


def active_versions(db: Session, on: date) -> list[RuleVersion]:
    rules = db.execute(select(Rule).order_by(Rule.key)).scalars().all()
    return [v for r in rules if (v := effective_on(r.versions, on)) is not None]


def compare(db: Session, rule_id: str, from_id: str, to_id: str) -> dict:
    a, b = get_version(db, rule_id, from_id), get_version(db, rule_id, to_id)

    def content(v: RuleVersion) -> dict:
        return {
            "definition": v.definition,
            "effective_from": v.effective_from.isoformat(),
            "effective_to": v.effective_to.isoformat() if v.effective_to else None,
            "source_reference": v.source_reference,
        }

    return {
        "from": {
            "id": a.id,
            "version_number": a.version_number,
            "status": a.status,
            "summary": definition_summary(validate_definition(a.definition)),
        },
        "to": {
            "id": b.id,
            "version_number": b.version_number,
            "status": b.status,
            "summary": definition_summary(validate_definition(b.definition)),
        },
        "changes": diff(content(a), content(b)),
    }


# ------------------------------------------------------------------ simulation (read-only)


@dataclass
class Proposal:
    rule_id: str
    definition: RuleDefinition
    label: str


def simulate(
    db: Session, user: User, applications: list[Application], proposals: list[Proposal], on: date
) -> list[dict]:
    """Compare baseline (rules in force on `on`) with baseline+proposals, for each application.

    Read-only: builds snapshots and evaluates in memory. It never writes rules, versions or validation runs.
    """
    from app.services.validation_service import build_snapshot  # local import: avoids a cycle

    _require(user, Permission.RULES_SIMULATE)
    baseline = active_versions(db, on)
    proposed_by_rule = {p.rule_id: p for p in proposals}
    rule_ids = sorted({v.rule_id for v in baseline} | set(proposed_by_rule))
    rules = {r.id: r for r in db.execute(select(Rule).where(Rule.id.in_(rule_ids))).scalars()}
    out = []
    for app in applications:
        snap = build_snapshot(db, app, on)
        rows = []
        for rid in rule_ids:
            base_v = next((v for v in baseline if v.rule_id == rid), None)
            before = engine.evaluate(validate_definition(base_v.definition), snap) if base_v else None
            prop = proposed_by_rule.get(rid)
            after = engine.evaluate(prop.definition, snap) if prop else before
            rows.append(
                {
                    "rule_id": rid,
                    "rule_key": rules[rid].key,
                    "rule_name": rules[rid].name,
                    "before": {
                        "version": base_v.version_number if base_v else None,
                        "outcome": before["outcome"] if before else "not_in_force",
                        "reason": before["reason"] if before else None,
                    },
                    "after": {
                        "version": prop.label if prop else (base_v.version_number if base_v else None),
                        "outcome": after["outcome"] if after else "not_in_force",
                        "reason": after["reason"] if after else None,
                        "trace": after["trace"] if after else [],
                    },
                    "changed": (before["outcome"] if before else "not_in_force")
                    != (after["outcome"] if after else "not_in_force"),
                }
            )
        out.append(
            {
                "application_id": app.id,
                "reference": app.reference,
                "title": app.title,
                "rules": rows,
                "changed": sum(r["changed"] for r in rows),
            }
        )
    return out
