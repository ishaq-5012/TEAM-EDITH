from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import ValidationError
from sqlalchemy import select

from app.api.deps import DbSession, audit_context, require_permission
from app.core.errors import NotFoundError
from app.core.roles import Permission, has_permission
from app.models.application import Application
from app.models.rules import Rule, RuleVersion
from app.models.user import User
from app.rules.schema import ALL_OPERATORS, OPERATORS, field_catalog, parse_definition
from app.rules.summary import definition_summary
from app.schemas.application import UserRef
from app.schemas.rules import (
    DefinitionCheck,
    DefinitionIn,
    DraftUpdate,
    NewVersionIn,
    RetireIn,
    ReviewIn,
    RuleCreate,
    RuleList,
    RuleListItem,
    RuleMetadataUpdate,
    RuleOut,
    SimulateIn,
    SimulationOut,
    TestCaseIn,
    TestCaseOut,
    TestRun,
    VersionOut,
)
from app.services import application_service, audit_service, rule_service

router = APIRouter(prefix="/rules", tags=["rules"])

Reader = Annotated[User, Depends(require_permission(Permission.RULES_READ))]
Manager = Annotated[User, Depends(require_permission(Permission.RULES_MANAGE))]
Publisher = Annotated[User, Depends(require_permission(Permission.RULES_PUBLISH))]
Simulator = Annotated[User, Depends(require_permission(Permission.RULES_SIMULATE))]


def _today() -> date:
    return datetime.now(UTC).date()


def _version_out(v: RuleVersion, in_force: RuleVersion | None) -> VersionOut:
    out = VersionOut.model_validate(v)
    out.summary = definition_summary(parse_definition(v.definition))
    out.in_force_today = in_force is not None and in_force.id == v.id
    return out


def _rule_out(db, rule: Rule) -> RuleOut:  # noqa: ANN001
    in_force = rule_service.effective_on(rule.versions, _today())
    return RuleOut(
        id=rule.id,
        key=rule.key,
        name=rule.name,
        description=rule.description,
        category=rule.category,
        owner=UserRef.model_validate(rule.owner),
        created_at=rule.created_at,
        updated_at=rule.updated_at,
        versions=[_version_out(v, in_force) for v in reversed(rule.versions)],
        test_cases=[TestCaseOut.model_validate(t) for t in rule_service.test_cases(db, rule.id)],
        disclaimer=rule_service.DISCLAIMER,
    )


def _fresh(db, rule_id: str) -> RuleOut:  # noqa: ANN001
    # Sessions keep objects after commit; reload so relationships (versions, reviewers) reflect the change.
    db.expire_all()
    return _rule_out(db, rule_service.get_rule(db, rule_id))


@router.get("", response_model=RuleList)
def list_rules(db: DbSession, user: Reader) -> RuleList:
    items = []
    for rule in db.execute(select(Rule).order_by(Rule.category, Rule.key)).scalars():
        in_force = rule_service.effective_on(rule.versions, _today())
        latest = rule.versions[-1]
        items.append(
            RuleListItem(
                id=rule.id,
                key=rule.key,
                name=rule.name,
                category=rule.category,
                owner=UserRef.model_validate(rule.owner),
                in_force_version=in_force.version_number if in_force else None,
                in_force_severity=in_force.definition.get("severity") if in_force else None,
                latest_version=latest.version_number,
                latest_status=latest.status,
                pending_approval=any(v.status == "pending_approval" for v in rule.versions),
                has_draft=any(v.status == "draft" for v in rule.versions),
            )
        )
    return RuleList(
        items=items,
        can_manage=has_permission(user.role, Permission.RULES_MANAGE),
        can_publish=has_permission(user.role, Permission.RULES_PUBLISH),
        disclaimer=rule_service.DISCLAIMER,
    )


@router.get("/catalog")
def catalog(_: Reader) -> dict:
    """Fields a rule may reference (with types) and the operators allowed for each type."""
    return {
        "fields": [
            {"ref": ref, **{k: (v.value if hasattr(v, "value") else v) for k, v in spec.items()}}
            for ref, spec in sorted(field_catalog().items())
        ],
        "operators": {t.value: ops for t, ops in OPERATORS.items()},
        "all_operators": ALL_OPERATORS,
        "outcomes": ["pass", "fail", "review", "insufficient", "not_applicable"],
    }


@router.post("/validate", response_model=DefinitionCheck)
def validate(body: DefinitionIn, _: Reader) -> DefinitionCheck:
    """Validate a definition and summarise it. Writes nothing."""
    try:
        d = parse_definition(body.definition)
    except ValidationError as exc:
        return DefinitionCheck(
            valid=False,
            summary=None,
            errors=[
                {"loc": ".".join(map(str, e["loc"])), "msg": e["msg"].removeprefix("Value error, ")}
                for e in exc.errors()
            ],
        )
    return DefinitionCheck(valid=True, errors=[], summary=definition_summary(d))


@router.post("", response_model=RuleOut, status_code=status.HTTP_201_CREATED)
def create_rule(body: RuleCreate, request: Request, db: DbSession, user: Manager) -> RuleOut:
    rule = rule_service.create_rule(db, audit_context(request, user), user, **body.model_dump())
    return _fresh(db, rule.id)


@router.post("/simulate", response_model=SimulationOut)
def simulate(body: SimulateIn, request: Request, db: DbSession, user: Simulator) -> SimulationOut:
    """What-if: compare rules in force with proposed versions or unsaved definitions. Read-only."""
    on = body.evaluation_date or _today()
    proposals = []
    for p in body.proposals:
        rule = rule_service.get_rule(db, p.rule_id)
        if p.version_id:
            v = rule_service.get_version(db, rule.id, p.version_id)
            proposals.append(
                rule_service.Proposal(
                    rule.id, rule_service.validate_definition(v.definition), f"v{v.version_number} ({v.status})"
                )
            )
        elif p.definition is not None:
            proposals.append(
                rule_service.Proposal(rule.id, rule_service.validate_definition(p.definition), "unsaved edit")
            )
        else:
            raise rule_service.InvalidRule("Each proposal needs a version_id or a definition")
    if body.application_ids:
        apps = [application_service.get_for_read(db, user, a) for a in body.application_ids]
    else:
        visible = application_service.visible_filter(user)
        stmt = select(Application).order_by(Application.updated_at.desc()).limit(50)
        apps = list(db.execute(stmt.where(visible) if visible is not None else stmt).scalars())
    results = rule_service.simulate(db, user, apps, proposals, on)
    # The audit entry is the only write a simulation makes, and it records the access to application data.
    audit_service.record(
        db,
        audit_context(request, user),
        "rule.simulated",
        entity_type="rule",
        summary=f"Simulated {len(proposals)} proposal(s) across {len(apps)} application(s)",
        data={"rule_ids": [p.rule_id for p in proposals], "applications": len(apps), "evaluation_date": on.isoformat()},
    )
    db.commit()
    return SimulationOut(
        evaluation_date=on,
        applications=results,
        side_effects="None: no rules, versions or validation runs were created or modified.",
    )


@router.get("/{rule_id}", response_model=RuleOut)
def get_rule(rule_id: str, db: DbSession, _: Reader) -> RuleOut:
    return _fresh(db, rule_id)


@router.patch("/{rule_id}", response_model=RuleOut)
def update_rule(rule_id: str, body: RuleMetadataUpdate, request: Request, db: DbSession, user: Manager) -> RuleOut:
    rule_service.update_rule_metadata(
        db, audit_context(request, user), user, rule_id, body.model_dump(exclude_unset=True)
    )
    return _fresh(db, rule_id)


@router.post("/{rule_id}/versions", response_model=RuleOut, status_code=status.HTTP_201_CREATED)
def new_version(rule_id: str, body: NewVersionIn, request: Request, db: DbSession, user: Manager) -> RuleOut:
    rule_service.new_version(db, audit_context(request, user), user, rule_id, body.from_version_id)
    return _fresh(db, rule_id)


@router.patch("/{rule_id}/versions/{version_id}", response_model=RuleOut)
def update_draft(
    rule_id: str, version_id: str, body: DraftUpdate, request: Request, db: DbSession, user: Manager
) -> RuleOut:
    rule_service.update_draft(
        db, audit_context(request, user), user, rule_id, version_id, body.model_dump(exclude_unset=True)
    )
    return _fresh(db, rule_id)


@router.post("/{rule_id}/versions/{version_id}/submit", response_model=RuleOut)
def submit(rule_id: str, version_id: str, request: Request, db: DbSession, user: Manager) -> RuleOut:
    rule_service.submit(db, audit_context(request, user), user, rule_id, version_id)
    return _fresh(db, rule_id)


@router.post("/{rule_id}/versions/{version_id}/approve", response_model=RuleOut)
def approve(rule_id: str, version_id: str, body: ReviewIn, request: Request, db: DbSession, user: Publisher) -> RuleOut:
    rule_service.approve(db, audit_context(request, user), user, rule_id, version_id, body.note)
    return _fresh(db, rule_id)


@router.post("/{rule_id}/versions/{version_id}/reject", response_model=RuleOut)
def reject(rule_id: str, version_id: str, body: ReviewIn, request: Request, db: DbSession, user: Publisher) -> RuleOut:
    rule_service.reject(db, audit_context(request, user), user, rule_id, version_id, body.note)
    return _fresh(db, rule_id)


@router.post("/{rule_id}/versions/{version_id}/retire", response_model=RuleOut)
def retire(rule_id: str, version_id: str, body: RetireIn, request: Request, db: DbSession, user: Publisher) -> RuleOut:
    rule_service.retire(db, audit_context(request, user), user, rule_id, version_id, body.reason)
    return _fresh(db, rule_id)


@router.get("/{rule_id}/compare")
def compare(
    rule_id: str, db: DbSession, _: Reader, from_: Annotated[str, Query(alias="from")], to: Annotated[str, Query()]
) -> dict:
    return rule_service.compare(db, rule_id, from_, to)


@router.post("/{rule_id}/test-cases", response_model=TestCaseOut, status_code=status.HTTP_201_CREATED)
def add_test_case(rule_id: str, body: TestCaseIn, request: Request, db: DbSession, user: Manager) -> TestCaseOut:
    tc = rule_service.add_test_case(db, audit_context(request, user), user, rule_id, **body.model_dump())
    return TestCaseOut.model_validate(tc)


@router.delete("/{rule_id}/test-cases/{case_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_test_case(rule_id: str, case_id: str, request: Request, db: DbSession, user: Manager) -> None:
    rule_service.delete_test_case(db, audit_context(request, user), user, rule_id, case_id)


@router.post("/{rule_id}/versions/{version_id}/test", response_model=TestRun)
def test_version(rule_id: str, version_id: str, db: DbSession, _: Reader) -> TestRun:
    """Run the rule's synthetic test cases against a stored version. Writes nothing."""
    v = rule_service.get_version(db, rule_id, version_id)
    return TestRun(
        **rule_service.run_tests(rule_service.validate_definition(v.definition), rule_service.test_cases(db, rule_id))
    )


@router.post("/{rule_id}/test-definition", response_model=TestRun)
def test_definition(rule_id: str, body: DefinitionIn, db: DbSession, _: Manager) -> TestRun:
    """Run the synthetic test cases against an unsaved definition (editor preview). Writes nothing."""
    rule = rule_service.get_rule(db, rule_id)
    if rule is None:
        raise NotFoundError("Rule not found")
    return TestRun(
        **rule_service.run_tests(
            rule_service.validate_definition(body.definition), rule_service.test_cases(db, rule.id)
        )
    )
