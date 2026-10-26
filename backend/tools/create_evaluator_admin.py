"""Create a separate SIH evaluator admin login without changing the existing admin account."""

import re

from sqlalchemy import select

from app.core.config import get_settings
from app.core.roles import Role
from app.core.security import verify_password
from app.db.session import SessionLocal
from app.models.user import User
from app.services import institution_service, user_service
from app.services.audit_service import AuditContext

EMAIL = "sih.admin@example.org"


def main() -> None:
    path = get_settings().evaluator_accounts_file
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    match = re.search(r"^admin\s+sih\.admin@example\.org\s+password:\s+(\S+)", existing, re.MULTILINE)
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == EMAIL))
        if user:
            if not match or not user.is_active or user.role != Role.ADMIN.value or not verify_password(match.group(1), user.password_hash):
                raise RuntimeError("Evaluator admin exists but its credential file does not match")
            print("Evaluator admin account already ready")
            return
        password = user_service.generate_password()
        institution = institution_service.get_or_create_default(db)
        user_service.create_user(
            db, AuditContext(request_id="sih-evaluator-admin"), email=EMAIL,
            full_name="SIH Evaluator Admin", role=Role.ADMIN, password=password,
            institution_id=institution.id,
        )
        db.commit()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as output:
        output.write(f"admin                {EMAIL:34} password: {password}  institution DEFAULT\n")
    print("Created SIH evaluator admin; credential saved in the evaluator accounts file")


if __name__ == "__main__":
    main()
