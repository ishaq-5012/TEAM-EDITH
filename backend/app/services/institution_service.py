"""Institutions: the tenant boundary.

Every user and application belongs to exactly one institution, and access never crosses it: not for administrators,
not for auditors. Roles say what a person may do; the institution says whose records they may do it to.
Institutions are created by the platform operator (CLI), not through the web API, because creating a tenant is not
something an institution's own administrator should be able to do.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, DomainError
from app.models.institution import DEFAULT_CODE, Institution
from app.models.user import User
from app.services import audit_service
from app.services.audit_service import AuditContext

_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{1,39}$")


def get_by_code(db: Session, code: str) -> Institution | None:
    return db.execute(select(Institution).where(Institution.code == code.strip().upper())).scalar_one_or_none()


def get_or_create_default(db: Session) -> Institution:
    inst = get_by_code(db, DEFAULT_CODE)
    if inst is None:
        inst = Institution(name="Default institution", code=DEFAULT_CODE)
        db.add(inst)
        db.flush()
    return inst


def create(db: Session, ctx: AuditContext, *, name: str, code: str) -> Institution:
    name, code = name.strip(), code.strip().upper()
    if len(name) < 3:
        raise DomainError("Institution name must be at least 3 characters", code="invalid_institution")
    if not _CODE_RE.match(code):
        raise DomainError(
            "Institution code: 2-40 characters, A-Z, 0-9, underscore or hyphen, starting with a letter or digit",
            code="invalid_institution",
        )
    if get_by_code(db, code):
        raise ConflictError("An institution with this code already exists", code="institution_exists")
    inst = Institution(name=name, code=code)
    db.add(inst)
    db.flush()
    audit_service.record(
        db, ctx, "institution.created", entity_type="institution", entity_id=inst.id,
        summary=f"Created institution {inst.code}", data={"name": inst.name, "code": inst.code},
    )
    return inst


def same_institution(a: User, institution_id: str | None) -> bool:
    """True only when both sides have an institution and it is the same one."""
    return a.institution_id is not None and a.institution_id == institution_id
