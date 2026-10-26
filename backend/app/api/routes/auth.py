from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select

from app.api.cookies import clear_session_cookies, set_session_cookies
from app.api.deps import CurrentAuth, DbSession, audit_context
from app.core.config import get_settings
from app.core.roles import permissions_for
from app.core.security import verify_password
from app.models.session import UserSession
from app.models.user import User
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    MeOut,
    RevokeResult,
    SessionInfo,
    SessionOut,
    UserOut,
)
from app.services import audit_service, auth_service, session_service, user_service

router = APIRouter(prefix="/auth", tags=["auth"])

EVALUATOR_ROLES = {
    "admin": ("Admin", "sih.admin@example.org"),
    "reviewer": ("Reviewer", "reviewer.demo@example.org"),
    "compliance_manager": ("Compliance Manager", "compliance.manager@example.org"),
    "auditor": ("Auditor", "auditor.demo@example.org"),
}


@router.get("/evaluator-credentials")
def evaluator_credentials(response: Response, db: DbSession) -> dict:
    """Opt-in public walkthrough accounts; never return arbitrary user credentials."""
    settings = get_settings()
    if not settings.evaluator_autofill or not settings.evaluator_accounts_file.is_file():
        raise HTTPException(status_code=404, detail="Evaluator sign-in is unavailable")
    response.headers["Cache-Control"] = "no-store"
    entries = {}
    for line in settings.evaluator_accounts_file.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"\s*(\S+)\s+(\S+)\s+password:\s+(\S+)(?:\s+institution\s+\S+)?\s*", line)
        if match:
            entries[match.group(2)] = match.group(3)
    accounts = []
    for role, (label, email) in EVALUATOR_ROLES.items():
        password = entries.get(email)
        user = db.scalar(select(User).where(User.email == email))
        if password and user and user.is_active and user.role == role and verify_password(password, user.password_hash):
            accounts.append({"role": role, "label": label, "email": email, "password": password})
    return {"accounts": accounts}


def build_me(user: User, session: UserSession) -> MeOut:
    return MeOut(
        **UserOut.model_validate(user).model_dump(),
        permissions=sorted(p.value for p in permissions_for(user.role)),
        session=SessionInfo(
            id=session.id,
            created_at=session.created_at,
            expires_at=session.expires_at,
            idle_expires_at=session.idle_expires_at,
            idle_timeout_minutes=get_settings().session_idle_minutes,
        ),
    )


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request, response: Response, db: DbSession) -> LoginResponse:
    ctx = audit_context(request)
    # If the browser still holds an old session cookie, end it: a login always starts fresh.
    old = request.cookies.get(get_settings().session_cookie_name)
    if old:
        prior = session_service.resolve(db, old).session
        if prior is not None:
            session_service.revoke(db, prior, "replaced_by_login")
    issued = auth_service.login(db, ctx, body.email, body.password, user_agent=request.headers.get("user-agent"))
    set_session_cookies(response, issued.session, issued.token, issued.csrf_token)
    return LoginResponse(user=build_me(issued.session.user, issued.session), csrf_token=issued.csrf_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def logout(request: Request, db: DbSession, auth: CurrentAuth) -> Response:
    auth_service.logout(db, audit_context(request, auth.user), auth.session)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookies(response)
    return response


@router.get("/me", response_model=MeOut)
def me(auth: CurrentAuth) -> MeOut:
    return build_me(auth.user, auth.session)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def change_password(body: ChangePasswordRequest, request: Request, db: DbSession, auth: CurrentAuth) -> None:
    user_service.change_password(
        db, audit_context(request, auth.user), auth.user, body.current_password, body.new_password,
        keep_session_id=auth.session.id,
    )


@router.get("/sessions", response_model=list[SessionOut])
def my_sessions(db: DbSession, auth: CurrentAuth) -> list[SessionOut]:
    return [
        SessionOut.model_validate(s).model_copy(update={"current": s.id == auth.session.id})
        for s in session_service.list_active(db, auth.user.id)
    ]


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def revoke_session(session_id: str, request: Request, db: DbSession, auth: CurrentAuth) -> Response:
    """Revoke one of your own sessions (or any session with sessions:manage)."""
    revoked = session_service.revoke_by_id(db, audit_context(request, auth.user), auth.user, session_id)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    if revoked.id == auth.session.id:
        clear_session_cookies(response)
    return response


@router.post("/sessions/revoke-others", response_model=RevokeResult)
def revoke_other_sessions(request: Request, db: DbSession, auth: CurrentAuth) -> RevokeResult:
    count = session_service.revoke_all_for_user(db, auth.user.id, "revoked_by_owner", except_id=auth.session.id)
    audit_service.record(
        db, audit_context(request, auth.user), "auth.sessions_revoked", entity_type="user", entity_id=auth.user.id,
        summary="User signed out all other sessions", data={"sessions_revoked": count},
    )
    db.commit()
    return RevokeResult(revoked=count)
