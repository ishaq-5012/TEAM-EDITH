from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import DbSession, audit_context, require_permission
from app.api.routes.evidence import finding_out, page_sizes
from app.core.roles import Permission, has_permission
from app.models.user import User
from app.schemas.application import UserRef
from app.schemas.review import (
    ActionIn,
    ActionOut,
    AppRef,
    CorrectionIn,
    PreviousItem,
    QueueOut,
    QueueRow,
    ResultOut,
    ReviewActionOut,
    ReviewDetail,
    ReviewItemOut,
    RunRef,
)
from app.services import review_service

router = APIRouter(prefix="/reviews", tags=["review"])

# Reading the queue needs application read access; each item is further limited to visible applications.
Reader = Annotated[User, Depends(require_permission(Permission.APPLICATIONS_READ))]
# Acting needs review:resolve; the service additionally requires edit access to the item's application.
Resolver = Annotated[User, Depends(require_permission(Permission.REVIEW_RESOLVE))]


def _action_out(r: review_service.ActionResult) -> ActionOut:
    return ActionOut(
        item=ReviewItemOut.model_validate(r.item),
        action=ReviewActionOut.model_validate(r.action),
        replayed=r.replayed,
        revalidation=r.revalidation,
    )


@router.get("", response_model=QueueOut)
def queue(
    db: DbSession,
    user: Reader,
    status: Annotated[
        str, Query(pattern=r"^(active|closed|all|open|awaiting_document|escalated|confirmed|dismissed|resolved)$")
    ] = "active",
    category: Annotated[Literal["failure", "uncertain", "missing"] | None, Query()] = None,
    assignee: Annotated[str | None, Query(max_length=32)] = None,
    severity: Annotated[Literal["critical", "high", "medium", "low"] | None, Query()] = None,
    application_id: Annotated[str | None, Query(max_length=32)] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> QueueOut:
    f = review_service.QueueFilters(status, category, assignee, severity, application_id, q, limit, offset)
    rows, total, counts = review_service.list_items(db, user, f)
    return QueueOut(
        items=[QueueRow(item=ReviewItemOut.model_validate(i), application=AppRef.model_validate(a)) for i, a in rows],
        total=total,
        limit=limit,
        offset=offset,
        counts=counts,
        can_act_anywhere=has_permission(user.role, Permission.REVIEW_RESOLVE),
    )


@router.get("/{item_id}", response_model=ReviewDetail)
def get_item(item_id: str, db: DbSession, user: Reader) -> ReviewDetail:
    d = review_service.detail(db, user, item_id)
    sizes = page_sizes(db, d["evidence"]["findings"])
    return ReviewDetail(
        item=ReviewItemOut.model_validate(d["item"]),
        application=AppRef.model_validate(d["application"]),
        result=ResultOut.model_validate(d["result"]),
        run=RunRef.model_validate(d["run"]),
        rule=d["rule"],
        uncertainty=d["uncertainty"],
        fields=d["fields"],
        evidence={
            "analysis_id": d["evidence"]["analysis_id"],
            "findings": [finding_out(f, sizes).model_dump(mode="json") for f in d["evidence"]["findings"]],
        },
        history=[ReviewActionOut.model_validate(a) for a in d["history"]],
        previous_items=[PreviousItem.model_validate(p) for p in d["previous_items"]],
        rule_runs=d["rule_runs"],
        permissions=d["permissions"],
    )


@router.get("/{item_id}/assignees", response_model=list[UserRef])
def assignees(item_id: str, db: DbSession, user: Resolver) -> list[UserRef]:
    return [UserRef.model_validate(u) for u in review_service.assignees(db, user, item_id)]


@router.post("/{item_id}/actions", response_model=ActionOut)
def act(item_id: str, body: ActionIn, request: Request, db: DbSession, user: Resolver) -> ActionOut:
    """Assign, comment, escalate, request a document, resume, confirm, dismiss or reopen.

    `expected_version` must match the item's current version (409 `stale_item` otherwise). A repeated
    `request_id` returns the original result with `replayed: true` instead of acting twice.
    """
    result = review_service.act(
        db,
        audit_context(request, user),
        user,
        item_id,
        review_service.ActionIn(
            action=body.action,
            expected_version=body.expected_version,
            request_id=body.request_id,
            reason=body.reason,
            assignee_id=body.assignee_id,
            document_description=body.document_description,
        ),
    )
    return _action_out(result)


@router.post("/{item_id}/corrections", response_model=ActionOut)
def correct(item_id: str, body: CorrectionIn, request: Request, db: DbSession, user: Resolver) -> ActionOut:
    """Append a correction to an extracted field (the original extraction is kept) and revalidate if it matters."""
    result = review_service.correct(
        db,
        audit_context(request, user),
        user,
        item_id,
        expected_version=body.expected_version,
        request_id=body.request_id,
        document_id=body.document_id,
        field_id=body.field_id,
        value=body.value,
        reason=body.reason,
    )
    return _action_out(result)
