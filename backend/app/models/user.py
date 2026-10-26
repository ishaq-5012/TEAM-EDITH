from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String, func
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.roles import LEGACY_ROLE_VALUES, Role
from app.db.base import Base, IdMixin, TimestampMixin, UTCDateTime
from app.models.institution import Institution

_ROLE_CHECK = "role IN (" + ", ".join(f"'{r}'" for r in LEGACY_ROLE_VALUES) + ")"


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint(_ROLE_CHECK, name="role_valid"),)

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    legacy_role: Mapped[str] = mapped_column("role", String(40), nullable=False)
    officer_role: Mapped[str | None] = mapped_column(String(40), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    password_changed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    # Tenant boundary. Nullable only because SQLite cannot add a NOT NULL FK without a table rebuild; the service
    # layer always sets it and tests assert that no row is left without one.
    institution_id: Mapped[str | None] = mapped_column(
        ForeignKey("institutions.id"), nullable=True, index=True
    )
    institution: Mapped[Institution | None] = relationship(lazy="joined")

    @hybrid_property
    def role(self) -> str:
        return self.officer_role or self.legacy_role

    @role.inplace.setter
    def _set_role(self, value: str | Role) -> None:
        selected = Role(value)
        if selected is Role.SECOND_APPROVER:
            # The old constrained column remains a storage fallback only;
            # every authorization path reads the effective role above.
            self.legacy_role = Role.AUDITOR.value
            self.officer_role = selected.value
        else:
            self.legacy_role = selected.value
            self.officer_role = None

    @role.inplace.expression
    @classmethod
    def _role_expression(cls):  # noqa: ANN206
        return func.coalesce(cls.officer_role, cls.legacy_role)

    def owner_ids(self) -> set[str]:
        # A user record is "owned" by that user (self-service profile/sessions).
        return {self.id}
