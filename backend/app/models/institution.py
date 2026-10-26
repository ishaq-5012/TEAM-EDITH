"""Institutions: the tenant boundary. Users and applications belong to exactly one institution."""

from __future__ import annotations

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin

DEFAULT_CODE = "DEFAULT"


class Institution(IdMixin, TimestampMixin, Base):
    __tablename__ = "institutions"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Short stable identifier (for example a registration or AISHE-style code the institution supplies).
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
