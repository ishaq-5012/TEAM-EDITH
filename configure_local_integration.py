"""Idempotently connect the two local development apps without resetting their data.

Run from the repository root with backend's Python after `alembic upgrade head`.
Secrets are written to ignored .env files and never printed.
"""

from __future__ import annotations

import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
PORTAL = ROOT / "mock-aicte-portal"


def read_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return dict(line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines()
                if "=" in line and not line.lstrip().startswith("#"))


def upsert_env(path: Path, updates: dict[str, str]) -> None:
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    keys = set()
    output = []
    for line in existing:
        key = line.split("=", 1)[0] if "=" in line and not line.lstrip().startswith("#") else None
        if key in updates:
            output.append(f"{key}={updates[key]}")
            keys.add(key)
        else:
            output.append(line)
    output.extend(f"{key}={value}" for key, value in updates.items() if key not in keys)
    path.write_text("\n".join(output) + "\n", encoding="utf-8")


def main() -> None:
    backend_env = BACKEND / ".env"
    portal_env = PORTAL / ".env"
    current = read_env(backend_env)
    shared = current.get("VERIFYFLOW_PORTAL_SHARED_SECRET") or secrets.token_urlsafe(48)
    owner_email = current.get("VERIFYFLOW_PORTAL_OWNER_EMAIL") or "portal.intake@example.org"

    sys.path.insert(0, str(BACKEND))
    from sqlalchemy import select
    from app.core.roles import Role
    from app.db.session import SessionLocal
    from app.models.user import User
    from app.services import user_service
    from app.services.audit_service import AuditContext

    with SessionLocal() as db:
        owner = db.execute(select(User).where(User.email == owner_email)).scalar_one_or_none()
        if owner is None:
            owner = user_service.create_user(db, AuditContext(request_id="local-integration-setup"),
                email=owner_email, full_name="Portal Intake Service", role=Role.REVIEWER,
                password=secrets.token_urlsafe(40))
            db.commit()
        if owner.role != Role.REVIEWER.value or not owner.is_active or not owner.institution_id:
            raise RuntimeError("The configured portal owner must be an active reviewer in a workspace")

    upsert_env(backend_env, {"VERIFYFLOW_PORTAL_SHARED_SECRET": shared,
                             "VERIFYFLOW_PORTAL_OWNER_EMAIL": owner_email})
    upsert_env(portal_env, {"SECRET_KEY": read_env(portal_env).get("SECRET_KEY") or secrets.token_urlsafe(48),
                            "VERIFYFLOW_INTAKE_URL": "http://127.0.0.1:8000",
                            "VERIFYFLOW_INTAKE_SECRET": shared})
    print("Local portal integration configured. Restart both web servers, then run `py -3.11 manage.py sync` from mock-aicte-portal.")


if __name__ == "__main__":
    main()
