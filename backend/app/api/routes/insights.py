from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.api.deps import DbSession, audit_context, require_permission
from app.core.roles import Permission
from app.models.user import User
from app.services import export_service, insights_service

router = APIRouter(tags=["insights"])

SystemReader = Annotated[User, Depends(require_permission(Permission.SYSTEM_READ))]
AppReader = Annotated[User, Depends(require_permission(Permission.APPLICATIONS_READ))]
RuleReader = Annotated[User, Depends(require_permission(Permission.RULES_READ))]
Exporter = Annotated[User, Depends(require_permission(Permission.EXPORTS_CREATE))]

DateFrom = Annotated[date | None, Query(alias="from", description="Window start (UTC date, inclusive)")]
DateTo = Annotated[date | None, Query(alias="to", description="Window end (UTC date, inclusive)")]
AppType = Annotated[str | None, Query(max_length=60)]
Synthetic = Annotated[bool, Query(description="Include synthetic demo applications")]
Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0)]


@router.get("/insights/definitions")
def definitions(_: SystemReader) -> list[dict[str, Any]]:
    """Every metric's definition, time basis, data source and de-duplication rule."""
    return insights_service.definitions()


@router.get("/insights/overview")
def overview(
    db: DbSession, user: SystemReader, date_from: DateFrom = None, date_to: DateTo = None,
    application_type: AppType = None, include_synthetic: Synthetic = True,
) -> dict[str, Any]:
    """Current-state and window aggregates over the applications this user can see."""
    scope = insights_service.make_scope(user, date_from, date_to, application_type, include_synthetic)
    return insights_service.overview(db, scope)


@router.get("/insights/review")
def review(
    db: DbSession, user: AppReader, date_from: DateFrom = None, date_to: DateTo = None,
    application_type: AppType = None, include_synthetic: Synthetic = True,
) -> dict[str, Any]:
    """Backlog by status, category and age; workload per assignee; false positives from reviewer decisions."""
    scope = insights_service.make_scope(user, date_from, date_to, application_type, include_synthetic)
    return insights_service.review(db, scope)


@router.get("/insights/rules")
def rules(
    db: DbSession, user: RuleReader, date_from: DateFrom = None, date_to: DateTo = None,
    application_type: AppType = None, include_synthetic: Synthetic = True, limit: Limit = 25, offset: Offset = 0,
) -> dict[str, Any]:
    """Rule-version usage and the validation run history in the window."""
    scope = insights_service.make_scope(user, date_from, date_to, application_type, include_synthetic)
    return insights_service.rules(db, scope, limit=limit, offset=offset)


@router.get("/insights/rule-governance")
def rule_governance(
    db: DbSession, user: RuleReader, date_from: DateFrom = None, date_to: DateTo = None,
    rule_id: Annotated[str | None, Query(max_length=32)] = None, limit: Limit = 50, offset: Offset = 0,
) -> dict[str, Any]:
    """Rule-version lifecycle events (created, submitted, approved, rejected, retired) in the window."""
    scope = insights_service.make_scope(user, date_from, date_to)
    return insights_service.governance(db, scope, rule_id, limit=limit, offset=offset)


# ------------------------------------------------------------------ exports


class ExportIn(BaseModel):
    dataset: str = Field(max_length=40)
    format: str = Field(default="csv", pattern="^(csv|json)$")
    date_from: date | None = None
    date_to: date | None = None
    application_type: str | None = Field(default=None, max_length=60)
    include_synthetic: bool = True
    # Sensitive exports only: explicit opt-in plus a recorded reason.
    include_document_values: bool = False
    reason: str | None = Field(default=None, max_length=500)
    # audit_events only. An action ending in "." matches a prefix, e.g. "rule.".
    action: str | None = Field(default=None, max_length=100)
    entity_type: str | None = Field(default=None, max_length=60)


@router.get("/exports/datasets")
def export_datasets(user: SystemReader) -> list[dict[str, Any]]:
    """The export datasets, what each contains, and whether this user may export it."""
    return export_service.datasets_for(user)


@router.post("/exports")
def create_export(body: ExportIn, request: Request, db: DbSession, user: Exporter) -> Response:
    """Build and download an export. Recorded in the audit chain (export.created / export.denied)."""
    scope = insights_service.make_scope(
        user, body.date_from, body.date_to, body.application_type, body.include_synthetic
    )
    f = export_service.export(
        db, audit_context(request, user), user, scope,
        export_service.ExportRequest(
            dataset=body.dataset, format=body.format, include_document_values=body.include_document_values,
            reason=body.reason, action=body.action, entity_type=body.entity_type,
        ),
    )
    return Response(
        content=f.content,
        media_type=f.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{f.filename}"',
            "X-Export-Rows": str(f.rows),
            "X-Export-Truncated": "true" if f.truncated else "false",
            "X-Export-Audit-Seq": str(f.audit_seq),
            "Access-Control-Expose-Headers": "Content-Disposition, X-Export-Rows, X-Export-Truncated",
        },
    )
