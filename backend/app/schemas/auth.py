from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, EmailStr, Field, field_validator

from app.core.roles import Role
from app.core.security import password_strength_error
from app.schemas.common import ORMModel


def _strong(value: str) -> str:
    err = password_strength_error(value)
    if err:
        raise ValueError(err)
    return value


StrongPassword = Annotated[str, Field(max_length=256), AfterValidator(_strong)]
Reason = Annotated[str, Field(min_length=3, max_length=500)]


class LoginRequest(BaseModel):
    # Format is enforced when accounts are created; login only looks the identifier up.
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)


class InstitutionOut(ORMModel):
    id: str
    name: str
    code: str


class UserOut(ORMModel):
    id: str
    email: str
    full_name: str
    role: Role
    is_active: bool
    last_login_at: datetime | None
    password_changed_at: datetime | None
    created_at: datetime
    institution: InstitutionOut | None = None


class SessionInfo(BaseModel):
    id: str
    created_at: datetime
    expires_at: datetime
    idle_expires_at: datetime
    idle_timeout_minutes: int


class MeOut(UserOut):
    permissions: list[str]
    session: SessionInfo


class LoginResponse(BaseModel):
    user: MeOut
    # Also set as a readable cookie; returned here so the SPA need not parse cookies after login.
    csrf_token: str


class SessionOut(ORMModel):
    id: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    idle_expires_at: datetime
    ip_address: str | None
    user_agent: str | None
    current: bool = False


class RevokeResult(BaseModel):
    revoked: int


class RevokeSessionsRequest(BaseModel):
    reason: Reason


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: StrongPassword


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    role: Role
    password: StrongPassword

    @field_validator("full_name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Full name is required")
        return v


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    role: Role | None = None
    is_active: bool | None = None
    reason: Reason


class PasswordReset(BaseModel):
    new_password: StrongPassword
    reason: Reason
