from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, EmailStr, Field, StringConstraints

from app.models.application import ApplicationStatus, DocumentStatus, JobStatus, MemberRole
from app.schemas.auth import InstitutionOut
from app.schemas.common import ORMModel

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)]
AppType = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=60)]
OptName = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)]


class UserRef(ORMModel):
    id: str
    full_name: str
    email: str


class ApplicationCreate(BaseModel):
    title: Title
    application_type: AppType
    applicant_name: OptName | None = None
    description: Description = ""


class ApplicationUpdate(BaseModel):
    title: Title | None = None
    application_type: AppType | None = None
    applicant_name: OptName | None = None
    description: Description | None = None


class TransitionRequest(BaseModel):
    action: Literal["complete", "approve", "return", "reopen", "archive", "restore"]
    reason: str = Field(min_length=3, max_length=500)


class MemberAdd(BaseModel):
    email: EmailStr
    role: MemberRole


class MemberOut(ORMModel):
    user: UserRef
    role: MemberRole
    created_at: datetime


class ApplicationSummary(ORMModel):
    id: str
    reference: str
    title: str
    applicant_name: str | None
    application_type: str
    status: ApplicationStatus
    review_stage: Literal["reviewer", "audit", "approved"] = "reviewer"
    owner: UserRef
    document_count: int
    created_at: datetime
    updated_at: datetime
    is_synthetic: bool = False  # created by the development-only seed-demo command
    institution: InstitutionOut | None = None


class ApplicationPermissions(BaseModel):
    """Computed by the server for the current user. The UI shapes itself from this; the API enforces it."""

    can_edit: bool
    can_upload: bool
    can_manage_members: bool
    allowed_actions: list[Literal["complete", "approve", "return", "reopen", "archive", "restore"]]


class ApplicationDetail(ApplicationSummary):
    description: str
    archived_at: datetime | None
    reviewer_completed_at: datetime | None = None
    audited_at: datetime | None = None
    audit_note: str | None = None
    members: list[MemberOut]
    document_status_counts: dict[str, int]
    permissions: ApplicationPermissions


class ApplicationListOut(BaseModel):
    items: list[ApplicationSummary]
    total: int
    limit: int
    offset: int
    application_types: list[str]
    can_create: bool


class JobOut(ORMModel):
    id: str
    kind: str
    status: JobStatus
    attempt: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    error_message: str | None
    result: dict[str, Any]


class DocumentOut(ORMModel):
    """Note: storage_key and filesystem paths are deliberately absent."""

    id: str
    application_id: str
    original_filename: str
    document_type: str | None
    declared_mime: str | None
    detected_mime: str
    size_bytes: int
    sha256: str
    page_count: int | None
    status: DocumentStatus
    uploaded_by: UserRef
    created_at: datetime
    updated_at: datetime
    latest_job: JobOut | None
    can_retry: bool = False


class DocumentDetail(DocumentOut):
    jobs: list[JobOut]


class UploadLimits(BaseModel):
    max_upload_bytes: int
    max_pdf_pages: int
    max_documents_per_application: int
    accepted: dict[str, list[str]]  # MIME -> extensions
