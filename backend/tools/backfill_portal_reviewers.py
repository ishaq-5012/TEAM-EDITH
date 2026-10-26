"""Route pre-existing portal applications awaiting review through the current reviewer policy."""

from fastapi import Request
from sqlalchemy import select

from app.api.routes.portal_intake import _route_review
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.application import Application
from app.models.portal_intake import PortalSubmission
from app.models.user import User


def main() -> None:
    with SessionLocal() as db:
        actor = db.scalar(select(User).where(User.email == get_settings().portal_owner_email))
        if actor is None:
            raise RuntimeError("Portal intake account is unavailable")
        apps = db.scalars(select(Application).join(PortalSubmission,
            PortalSubmission.application_id == Application.id).where(
                Application.status == "needs_review", Application.review_stage == "reviewer").distinct()).all()
        request = Request({"type": "http", "method": "POST", "path": "/maintenance/review-routing", "headers": []})
        for app in apps:
            _route_review(db, request, actor, app.id)
            db.expire(app)
            print(app.reference, sorted(m.user.email for m in app.members))


if __name__ == "__main__":
    main()
