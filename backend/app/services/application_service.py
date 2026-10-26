"""Applications: access policy, CRUD, filtering, lifecycle transitions and membership."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import ColumnElement, and_, false, func, or_, select
from sqlalchemy.orm import Session

from app.core.authz import authorize_owned
from app.core.errors import ConflictError, DomainError, NotFoundError
from app.core.roles import Permission, has_permission
from app.core.roles import Role
from app.db.base import utcnow
from app.models.application import (
    Application,
    ApplicationMember,
    ApplicationStatus,
    Document,
    DocumentStatus,
    MemberRole,
)
from app.models.user import User
from app.services import audit_service, institution_service
from app.services.audit_service import AuditContext

S = ApplicationStatus
_REF_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"  # no 0/O/1/I/L ambiguity

TransitionAction = Literal["complete", "approve", "return", "reopen", "archive", "restore"]


class ApplicationForbidden(DomainError):
    status_code = 403
    code = "forbidden"


class ApplicationArchived(ConflictError):
    code = "application_archived"


# ------------------------------------------------------------------ access policy


def _reads_all(user: User) -> bool:
    return has_permission(user.role, Permission.APPLICATIONS_READ_ALL)


def can_edit(user: User, app: Application) -> bool:
    """Edit details, upload, retry processing."""
    if not has_permission(user.role, Permission.APPLICATIONS_WRITE):
        return False
    return user.id in app.editor_ids() or _reads_all(user)


def can_manage(user: User, app: Application) -> bool:
    """Manage members, archive and restore: the owner, or a role with oversight of all applications."""
    if not has_permission(user.role, Permission.APPLICATIONS_WRITE):
        return False
    return user.id == app.owner_id or _reads_all(user)


def get_for_read(db: Session, user: User, application_id: str) -> Application:
    app = db.get(Application, application_id)
    if app is not None and not institution_service.same_institution(user, app.institution_id):
        app = None  # another institution's record: indistinguishable from "does not exist", even for admins
    authorize_owned(user, app, override=Permission.APPLICATIONS_READ_ALL, label="Application")
    assert app is not None
    return app


def get_for_edit(db: Session, user: User, application_id: str) -> Application:
    app = get_for_read(db, user, application_id)
    if not can_edit(user, app):
        raise ApplicationForbidden("You can view this application but not change it")
    return app


def ensure_mutable(app: Application) -> None:
    if app.status == S.ARCHIVED.value:
        raise ApplicationArchived("This application is archived. Restore it before making changes.")


def visible_filter(user: User) -> ColumnElement[bool]:
    """WHERE clause limiting a query to applications the user can see.

    Always scoped to the user's own institution first; within it, roles with oversight see every application and
    others only those they own or belong to. A user without an institution sees nothing.
    """
    if user.institution_id is None:
        return false()
    in_institution = Application.institution_id == user.institution_id
    if _reads_all(user):
        return in_institution
    member_apps = select(ApplicationMember.application_id).where(ApplicationMember.user_id == user.id)
    return and_(in_institution, or_(Application.owner_id == user.id, Application.id.in_(member_apps)))


# ------------------------------------------------------------------ create / list / update


def _new_reference(db: Session) -> str:
    year = datetime.now(UTC).year
    for _ in range(10):
        ref = f"APP-{year}-" + "".join(secrets.choice(_REF_ALPHABET) for _ in range(6))
        if not db.execute(select(Application.id).where(Application.reference == ref)).first():
            return ref
    raise ConflictError("Could not allocate a unique reference; try again")


def create(
    db: Session, ctx: AuditContext, user: User, *, title: str, application_type: str,
    applicant_name: str | None, description: str,
) -> Application:
    if user.institution_id is None:
        raise DomainError("Your account is not assigned to an institution", code="no_institution")
    app = Application(
        institution_id=user.institution_id,
        reference=_new_reference(db),
        title=title.strip(),
        application_type=application_type.strip(),
        applicant_name=(applicant_name or "").strip() or None,
        description=description.strip(),
        status=S.DRAFT.value,
        owner_id=user.id,
    )
    db.add(app)
    db.flush()
    audit_service.record(
        db, ctx, "application.created", entity_type="application", entity_id=app.id,
        summary=f"Created application {app.reference}",
        data={"reference": app.reference, "title": app.title, "application_type": app.application_type},
    )
    db.commit()
    return app


@dataclass(frozen=True)
class ListFilters:
    statuses: list[str]
    q: str | None
    application_type: str | None
    scope: Literal["all", "mine"]
    sort: Literal["updated_desc", "created_desc", "reference_asc", "title_asc"]
    limit: int
    offset: int


_SORTS = {
    "updated_desc": Application.updated_at.desc(),
    "created_desc": Application.created_at.desc(),
    "reference_asc": Application.reference.asc(),
    "title_asc": Application.title.asc(),
}


def _like(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def list_visible(db: Session, user: User, f: ListFilters) -> tuple[list[tuple[Application, int]], int]:
    doc_count = (
        select(Document.application_id, func.count().label("n")).group_by(Document.application_id).subquery()
    )
    conditions = []
    visible = visible_filter(user)
    if visible is not None:
        conditions.append(visible)
    if f.scope == "mine":
        member_apps = select(ApplicationMember.application_id).where(ApplicationMember.user_id == user.id)
        conditions.append(or_(Application.owner_id == user.id, Application.id.in_(member_apps)))
    if f.statuses:
        conditions.append(Application.status.in_(f.statuses))
    if f.application_type:
        conditions.append(Application.application_type == f.application_type)
    if f.q:
        pattern = _like(f.q.strip())
        conditions.append(
            or_(
                Application.title.ilike(pattern, escape="\\"),
                Application.reference.ilike(pattern, escape="\\"),
                Application.applicant_name.ilike(pattern, escape="\\"),
            )
        )
    total = db.execute(select(func.count()).select_from(Application).where(*conditions)).scalar_one()
    rows = db.execute(
        select(Application, func.coalesce(doc_count.c.n, 0))
        .outerjoin(doc_count, doc_count.c.application_id == Application.id)
        .where(*conditions)
        .order_by(_SORTS[f.sort], Application.id)
        .limit(f.limit)
        .offset(f.offset)
    ).all()
    return [(a, int(n)) for a, n in rows], total


def distinct_types(db: Session, user: User) -> list[str]:
    stmt = select(Application.application_type).distinct().order_by(Application.application_type)
    visible = visible_filter(user)
    if visible is not None:
        stmt = stmt.where(visible)
    return list(db.execute(stmt).scalars())


def update(
    db: Session, ctx: AuditContext, user: User, application_id: str, changes: dict[str, str | None]
) -> Application:
    app = get_for_edit(db, user, application_id)
    ensure_mutable(app)
    before, after = {}, {}
    for field, value in changes.items():
        value = value.strip() if isinstance(value, str) else value
        if field == "applicant_name":
            value = value or None
        if getattr(app, field) != value:
            before[field] = getattr(app, field)
            after[field] = value
            setattr(app, field, value)
    if not after:
        raise DomainError("No changes supplied", code="no_changes")
    audit_service.record(
        db, ctx, "application.updated", entity_type="application", entity_id=app.id,
        summary=f"Updated {app.reference}", data={"before": before, "after": after},
    )
    db.commit()
    return app


# ------------------------------------------------------------------ lifecycle


def document_counts(db: Session, application_id: str) -> dict[str, int]:
    rows = db.execute(
        select(Document.status, func.count()).where(Document.application_id == application_id).group_by(Document.status)
    ).all()
    return {status: n for status, n in rows}


def _in_flight(counts: dict[str, int]) -> int:
    return counts.get(DocumentStatus.QUEUED.value, 0) + counts.get(DocumentStatus.PROCESSING.value, 0)


def allowed_actions(db: Session, user: User, app: Application) -> list[TransitionAction]:
    if user.role == Role.AUDITOR.value:
        if app.status == S.NEEDS_REVIEW.value and app.review_stage == "audit" and _reads_all(user):
            return ["approve", "return"]
        return []
    if not can_edit(user, app):
        return []
    counts = document_counts(db, app.id)
    actions: list[TransitionAction] = []
    if app.status == S.NEEDS_REVIEW.value and sum(counts.values()) > 0 and _in_flight(counts) == 0:
        from app.models.review import ACTIVE_STATUSES, ReviewItem, ReviewStatus

        active_review = db.execute(select(ReviewItem.id).where(
            ReviewItem.application_id == app.id,
            ReviewItem.status.in_([status.value for status in ACTIVE_STATUSES]),
        ).limit(1)).first()
        from app.models.rules import ValidationRun

        from app.models.portal_intake import PortalSubmission

        latest = db.scalar(select(ValidationRun).where(ValidationRun.application_id == app.id)
                           .order_by(ValidationRun.created_at.desc(), ValidationRun.id.desc()))
        portal_case = db.scalar(select(PortalSubmission.id).where(PortalSubmission.application_id == app.id)) is not None
        clear = latest is None and not portal_case
        if latest is not None and latest.results:
            clear = True
            for result in latest.results:
                if result.outcome in ("pass", "not_applicable"):
                    continue
                decision = db.scalar(select(ReviewItem).where(
                    ReviewItem.application_id == app.id,
                    ReviewItem.current_result_id == result.id,
                    ReviewItem.status == ReviewStatus.DISMISSED.value,
                ).order_by(ReviewItem.updated_at.desc()))
                decider = db.get(User, decision.closed_by_id) if decision and decision.closed_by_id else None
                if decider is None or decider.role != Role.COMPLIANCE_MANAGER.value:
                    clear = False
                    break
        if user.role == Role.REVIEWER.value and app.review_stage == "reviewer" and active_review is None and clear:
            actions.append("complete")
    if app.status == S.COMPLETED.value and user.role == Role.COMPLIANCE_MANAGER.value:
        actions.append("reopen")
    if can_manage(user, app):
        if app.status != S.ARCHIVED.value and app.review_stage != "audit" and _in_flight(counts) == 0:
            actions.append("archive")
        if app.status == S.ARCHIVED.value:
            actions.append("restore")
    return actions


def transition(
    db: Session, ctx: AuditContext, user: User, application_id: str, action: TransitionAction, reason: str
) -> Application:
    app = get_for_read(db, user, application_id)
    if action not in ("approve", "return") and not can_edit(user, app):
        raise ApplicationForbidden("You can view this application but not change it")
    if action not in allowed_actions(db, user, app):
        if action in ("archive", "restore") and not can_manage(user, app):
            raise ApplicationForbidden("Only the owner or a compliance manager can archive or restore")
        raise ConflictError(f"Cannot {action} an application in status '{app.status}'", code="invalid_transition")
    before = app.status
    if action == "complete":
        app.review_stage = "audit"
        app.reviewer_completed_by_id = user.id
        app.reviewer_completed_at = utcnow()
    elif action == "approve":
        app.review_stage = "approved"
        app.status = S.COMPLETED.value
        app.auditor_id = user.id
        app.audited_at = utcnow()
        app.audit_note = reason
    elif action == "return":
        app.review_stage = "reviewer"
        app.auditor_id = user.id
        app.audited_at = utcnow()
        app.audit_note = reason
    elif action == "reopen":
        app.status = S.NEEDS_REVIEW.value
        app.review_stage = "reviewer"
    elif action == "archive":
        app.status_before_archive = app.status
        app.status = S.ARCHIVED.value
        app.archived_at = utcnow()
    elif action == "restore":
        app.status = app.status_before_archive or S.DRAFT.value
        app.status_before_archive = None
        app.archived_at = None
    event = {"complete": "application.sent_to_audit", "approve": "application.approved",
             "return": "application.returned_for_review", "reopen": "application.reopened",
             "archive": "application.archived", "restore": "application.restored"}[action]
    audit_service.record(
        db, ctx, event,
        entity_type="application", entity_id=app.id,
        summary=f"{app.reference}: {before} → {app.status}",
        data={"from": before, "to": app.status, "reason": reason},
    )
    db.commit()
    return app


def mark_processing(app: Application) -> None:
    """New documents put the application back into processing."""
    if app.status in (S.DRAFT.value, S.NEEDS_REVIEW.value, S.PROCESSING.value):
        app.status = S.PROCESSING.value
        app.review_stage = "reviewer"
        app.updated_at = utcnow()


def settle_after_processing(db: Session, app: Application) -> None:
    """When no document is queued or processing, a processing application moves to needs-review."""
    db.flush()  # sessions use autoflush=False; the caller's pending document status must be visible
    if app.status == S.PROCESSING.value and _in_flight(document_counts(db, app.id)) == 0:
        app.status = S.NEEDS_REVIEW.value
        app.updated_at = utcnow()


# ------------------------------------------------------------------ membership


def add_member(
    db: Session, ctx: AuditContext, user: User, application_id: str, email: str, role: MemberRole
) -> ApplicationMember:
    app = get_for_read(db, user, application_id)
    if not can_manage(user, app):
        raise ApplicationForbidden("Only the owner or a compliance manager can manage members")
    ensure_mutable(app)
    target = db.execute(select(User).where(User.email == email.strip().lower())).scalar_one_or_none()
    if target is None or not target.is_active or not institution_service.same_institution(user, target.institution_id):
        # Another institution's user is reported exactly like a missing one, so emails elsewhere cannot be probed.
        raise NotFoundError("No active user with that email address")
    if target.id == app.owner_id:
        raise ConflictError("The owner already has full access", code="already_owner")
    if not has_permission(target.role, Permission.APPLICATIONS_READ):
        raise DomainError("That user's role cannot access applications", code="role_cannot_access")
    if role == MemberRole.CONTRIBUTOR and not has_permission(target.role, Permission.APPLICATIONS_WRITE):
        raise DomainError(
            "That user's role is read-only; add them as a viewer instead", code="role_cannot_contribute"
        )
    existing = next((m for m in app.members if m.user_id == target.id), None)
    if existing:
        if existing.role == role.value:
            raise ConflictError("That user is already a member with this role", code="already_member")
        before = existing.role
        existing.role = role.value
        member = existing
        action, data = "application.member_updated", {"user_id": target.id, "from": before, "to": role.value}
    else:
        member = ApplicationMember(application_id=app.id, user_id=target.id, role=role.value, added_by_id=user.id)
        app.members.append(member)
        action, data = "application.member_added", {"user_id": target.id, "role": role.value}
    audit_service.record(
        db, ctx, action, entity_type="application", entity_id=app.id,
        summary=f"{target.email} is now a {role.value} on {app.reference}", data=data,
    )
    db.commit()
    db.refresh(member)
    return member


def remove_member(db: Session, ctx: AuditContext, user: User, application_id: str, member_user_id: str) -> None:
    app = get_for_read(db, user, application_id)
    if not can_manage(user, app):
        raise ApplicationForbidden("Only the owner or a compliance manager can manage members")
    ensure_mutable(app)
    member = next((m for m in app.members if m.user_id == member_user_id), None)
    if member is None:
        raise NotFoundError("Member not found")
    app.members.remove(member)
    audit_service.record(
        db, ctx, "application.member_removed", entity_type="application", entity_id=app.id,
        summary=f"Removed a member from {app.reference}", data={"user_id": member_user_id, "role": member.role},
    )
    db.commit()
