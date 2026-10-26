"""Session and CSRF cookie handling.

- Session cookie: HttpOnly, Secure, SameSite=Lax, Path=/, host-only (``__Host-`` prefix when
  Secure). JavaScript can never read it.
- CSRF cookie: Secure, SameSite=Strict, *readable* by the SPA, which echoes it back in the
  ``X-CSRF-Token`` header on state-changing requests. The server compares it with the hash
  stored on the session (synchronizer token), so a forged cookie alone is useless.
"""

from __future__ import annotations

from fastapi import Response

from app.core.config import get_settings
from app.models.session import UserSession
from app.services.session_service import effective_expiry

CSRF_HEADER = "X-CSRF-Token"


def set_session_cookies(response: Response, session: UserSession, token: str, csrf_token: str) -> None:
    settings = get_settings()
    # Cookie lifetime follows the absolute expiry; idle expiry is enforced server-side.
    max_age = int((session.expires_at - session.created_at).total_seconds())
    response.set_cookie(
        settings.session_cookie_name, token, max_age=max_age, path="/",
        secure=settings.cookie_secure, httponly=True, samesite="lax",
    )
    response.set_cookie(
        settings.csrf_cookie_name, csrf_token, max_age=max_age, path="/",
        secure=settings.cookie_secure, httponly=False, samesite="strict",
    )


def clear_session_cookies(response: Response) -> None:
    settings = get_settings()
    for name, samesite in ((settings.session_cookie_name, "lax"), (settings.csrf_cookie_name, "strict")):
        response.delete_cookie(name, path="/", secure=settings.cookie_secure, httponly=name.endswith("session"),
                               samesite=samesite)


def expiry_header_value(session: UserSession) -> str:
    return effective_expiry(session).isoformat()
