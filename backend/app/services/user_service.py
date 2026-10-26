from __future__ import annotations

import secrets
import string

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.authz import authorize_owned
from app.core.config import get_settings
from app.core.errors import ConflictError, DomainError, NotFoundError
from app.core.roles import Permission, Role
from app.core.security import hash_password, password_strength_error, verify_password
from app.db.base import utcnow
from app.models.session import LoginAttempt
from app.models.user import User
from app.services import audit_service, institution_service, session_service
from app.services.audit_service import AuditContext


def normalize_email(email: str) -> str:
    return email.strip().lower()


def validate_email_address(email: str) -> str:
    """Same rules as the API's EmailStr, applied on every creation path (API and CLI)."""
    try:
        return normalize_email(validate_email(email.strip(), check_deliverability=False).normalized)
    except EmailNotValidError as exc:
        raise DomainError(f"Invalid email address: {exc}", code="invalid_email") from None


def get_by_email(db: Session, email: str) -> User | None:
    return db.execute(select(User).where(User.email == normalize_email(email))).scalar_one_or_none()


def create_user(
    db: Session, ctx: AuditContext, *, email: str, full_name: str, role: Role, password: str,
    institution_id: str | None = None,
) -> User:
    email = validate_email_address(email)
    err = password_strength_error(password)
    if err:
        raise DomainError(err, code="weak_password")
    if get_by_email(db, email):
        raise ConflictError("A user with this email already exists")
    user = User(
        email=normalize_email(email),
        full_name=full_name.strip(),
        role=Role(role).value,
        password_hash=hash_password(password),
        institution_id=institution_id or institution_service.get_or_create_default(db).id,
    )
    db.add(user)
    db.flush()
    audit_service.record(
        db, ctx, "user.created", entity_type="user", entity_id=user.id,
        summary=f"Created user {user.email} with role {user.role}",
        data={"email": user.email, "role": user.role, "full_name": user.full_name, "institution_id": user.institution_id},
    )
    return user


class WrongCurrentPassword(DomainError):
    status_code = 400
    code = "wrong_current_password"


def change_password(
    db: Session, ctx: AuditContext, user: User, current: str, new: str, *, keep_session_id: str | None
) -> int:
    """Change own password. Revokes every *other* session; returns how many were revoked."""
    if not verify_password(current, user.password_hash):
        audit_service.record(
            db, ctx, "auth.password_change_failed", entity_type="user", entity_id=user.id,
            outcome="failure", summary="Current password incorrect",
        )
        db.commit()
        raise WrongCurrentPassword("Current password is incorrect")
    if verify_password(new, user.password_hash):
        raise DomainError("New password must differ from the current password", code="password_reused")
    user.password_hash = hash_password(new)
    user.password_changed_at = utcnow()
    revoked = session_service.revoke_all_for_user(db, user.id, "password_changed", except_id=keep_session_id)
    audit_service.record(
        db, ctx, "auth.password_changed", entity_type="user", entity_id=user.id,
        summary="User changed own password; other sessions revoked", data={"sessions_revoked": revoked},
    )
    db.commit()
    return revoked


def get_visible_user(db: Session, actor: User, user_id: str) -> User:
    """Users may read their own record; reading others requires users:read and the same institution."""
    user = db.get(User, user_id)
    if user is not None and user.id != actor.id and not institution_service.same_institution(actor, user.institution_id):
        user = None  # another institution's user: indistinguishable from "does not exist"
    authorize_owned(actor, user, override=Permission.USERS_READ, label="User")
    assert user is not None
    return user


def get_managed_user(db: Session, actor: User, user_id: str) -> User:
    """A user an administrator may change: only within the administrator's own institution."""
    user = db.get(User, user_id)
    if user is None or not institution_service.same_institution(actor, user.institution_id):
        raise NotFoundError("User not found")
    return user


def _active_admin_count(db: Session, institution_id: str | None) -> int:
    """Active administrators in one institution: each institution must always keep one."""
    return db.execute(
        select(func.count()).select_from(User).where(
            User.role == Role.ADMIN.value, User.is_active.is_(True), User.institution_id == institution_id
        )
    ).scalar_one()


def update_user(
    db: Session, ctx: AuditContext, user_id: str, *, full_name: str | None, role: Role | None,
    is_active: bool | None, reason: str,
) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found")
    before = {"full_name": user.full_name, "role": user.role, "is_active": user.is_active}

    removing_admin = user.role == Role.ADMIN.value and (
        (role is not None and role != Role.ADMIN) or is_active is False
    )
    if removing_admin and user.is_active and _active_admin_count(db, user.institution_id) <= 1:
        raise ConflictError("Cannot remove or deactivate the last active administrator of an institution")

    privileges_changed = False
    if full_name is not None:
        user.full_name = full_name.strip()
    if role is not None and role.value != user.role:
        user.role = role.value
        privileges_changed = True
    if is_active is not None and is_active != user.is_active:
        user.is_active = is_active
        privileges_changed = True

    after = {"full_name": user.full_name, "role": user.role, "is_active": user.is_active}
    if before == after:
        raise DomainError("No changes supplied", code="no_changes")
    revoked = 0
    if privileges_changed:
        # Role or status changes take effect immediately: existing sessions end.
        revoked = session_service.revoke_all_for_user(db, user.id, "privileges_changed")
    audit_service.record(
        db, ctx, "user.updated", entity_type="user", entity_id=user.id,
        summary=f"Updated user {user.email}",
        data={"before": before, "after": after, "reason": reason, "sessions_revoked": revoked},
    )
    db.commit()
    return user


def reset_password(db: Session, ctx: AuditContext, user_id: str, new_password: str, reason: str) -> None:
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found")
    user.password_hash = hash_password(new_password)
    user.password_changed_at = utcnow()
    revoked = session_service.revoke_all_for_user(db, user.id, "password_reset")
    # Clear sign-in throttling for this account so the user can sign in with the new password.
    db.execute(delete(LoginAttempt).where(LoginAttempt.email == user.email))
    audit_service.record(
        db, ctx, "user.password_reset", entity_type="user", entity_id=user.id,
        summary=f"Administrator reset password for {user.email}",
        data={"reason": reason, "sessions_revoked": revoked},
    )
    db.commit()


def revoke_sessions(db: Session, ctx: AuditContext, user_id: str, reason: str) -> int:
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found")
    revoked = session_service.revoke_all_for_user(db, user.id, "revoked_by_admin")
    audit_service.record(
        db, ctx, "auth.sessions_revoked", entity_type="user", entity_id=user.id,
        summary=f"Administrator signed {user.email} out everywhere",
        data={"reason": reason, "sessions_revoked": revoked},
    )
    db.commit()
    return revoked


def generate_password() -> str:
    """Random password meeting the strength policy (~120 bits of entropy)."""
    alphabet = string.ascii_letters + string.digits
    while True:
        body = "".join(secrets.choice(alphabet) for _ in range(20))
        candidate = f"{body[:10]}-{body[10:]}"
        if password_strength_error(candidate) is None:
            return candidate


def bootstrap_dev_admin(db: Session, ctx: AuditContext, *, email: str, full_name: str) -> tuple[User, str]:
    """Create the first administrator in a development database with a one-time random password.

    Refuses outside VERIFYFLOW_ENVIRONMENT=development and once any user exists, so it can
    never become a backdoor on a populated or production system.
    """
    if get_settings().environment != "development":
        raise DomainError(
            "bootstrap-dev-admin only runs when VERIFYFLOW_ENVIRONMENT=development. "
            "Use create-user (interactive password prompt) for other environments.",
            code="not_development",
        )
    if db.execute(select(func.count()).select_from(User)).scalar_one() > 0:
        raise ConflictError("Users already exist; bootstrap is only for an empty database")
    password = generate_password()
    user = create_user(db, ctx, email=email, full_name=full_name, role=Role.ADMIN, password=password)
    audit_service.record(
        db, ctx, "user.bootstrap_admin", entity_type="user", entity_id=user.id,
        summary="Development bootstrap administrator created (one-time generated password)",
    )
    db.commit()
    return user, password
