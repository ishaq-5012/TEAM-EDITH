from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import select

from app.api.deps import DbSession, audit_context, require_permission
from app.core.roles import Permission
from app.models.extraction import DocumentPage
from app.models.user import User
from app.schemas.evidence import AnalysisMeta, AnalyzeIn, EvidenceView, FindingOut
from app.services import application_service, evidence_service
from app.services.evidence_service import AnalysisState

router = APIRouter(prefix="/applications/{application_id}/evidence", tags=["evidence"])

Reader = Annotated[User, Depends(require_permission(Permission.DOCUMENTS_READ))]
Runner = Annotated[User, Depends(require_permission(Permission.VALIDATION_RUN))]


def page_sizes(db, findings) -> dict[tuple[str, int], tuple[float, float]]:  # noqa: ANN001
    """Displayed page sizes for every referenced page (the coordinate space of reference boxes)."""
    keys = {
        (r.extraction_run_id, r.page_number)
        for f in findings
        for r in f.references
        if r.extraction_run_id and r.page_number
    }
    if not keys:
        return {}
    rows = db.execute(
        select(DocumentPage.run_id, DocumentPage.page_number, DocumentPage.width, DocumentPage.height).where(
            DocumentPage.run_id.in_({k[0] for k in keys})
        )
    ).all()
    return {(r.run_id, r.page_number): (r.width, r.height) for r in rows}


def finding_out(f, sizes) -> FindingOut:  # noqa: ANN001
    out = FindingOut.model_validate(f)
    for ref in out.references:
        size = sizes.get((ref.extraction_run_id, ref.page_number))
        if size:
            ref.page_width, ref.page_height = size
    return out


def _view(db, user: User, application_id: str, state: AnalysisState) -> EvidenceView:  # noqa: ANN001
    app = application_service.get_for_read(db, user, application_id)
    sizes = page_sizes(db, state.analysis.findings)
    return EvidenceView(
        application_id=app.id,
        analysis=AnalysisMeta.model_validate(state.analysis),
        stale=state.stale,
        reused=state.reused,
        can_analyze=evidence_service.can_analyze(user, app) and app.status != "archived",
        findings=[finding_out(f, sizes) for f in state.analysis.findings],
    )


@router.get("", response_model=EvidenceView)
def get_current(application_id: str, db: DbSession, user: Reader) -> EvidenceView:
    """Current analysis with findings, relationships and evidence references. 404 `not_analyzed` if none yet."""
    return _view(db, user, application_id, evidence_service.get_state(db, user, application_id))


@router.post("/analyses", response_model=EvidenceView, status_code=status.HTTP_201_CREATED)
def run_analysis(
    application_id: str, body: AnalyzeIn, request: Request, response: Response, db: DbSession, user: Runner
) -> EvidenceView:
    """Run the deterministic cross-document analysis.

    Identical inputs reuse the current analysis (200) unless `force` is set (201 for a new analysis).
    """
    state = evidence_service.analyze(db, audit_context(request, user), user, application_id, force=body.force)
    if state.reused:
        response.status_code = status.HTTP_200_OK
    return _view(db, user, application_id, state)


@router.get("/analyses", response_model=list[AnalysisMeta])
def list_analyses(application_id: str, db: DbSession, user: Reader) -> list[AnalysisMeta]:
    return [AnalysisMeta.model_validate(a) for a in evidence_service.list_analyses(db, user, application_id)]


@router.get("/analyses/{analysis_id}", response_model=EvidenceView)
def get_analysis(application_id: str, analysis_id: str, db: DbSession, user: Reader) -> EvidenceView:
    """Any historical analysis, exactly as stored (snapshots are immutable)."""
    return _view(db, user, application_id, evidence_service.get_state(db, user, application_id, analysis_id))
