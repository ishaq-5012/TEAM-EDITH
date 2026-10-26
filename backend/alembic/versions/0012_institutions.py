"""Institutions: tenant boundary for users and applications.

Revision ID: 0012_institutions
Revises: 0011_synthetic_flag
Create Date: 2026-10-24

Creates `institutions`, adds nullable `institution_id` to `users` and `applications`, and backfills every existing
row into one "Default institution" so current data keeps working. Plain ADD COLUMN (no batch rebuild): rebuilding
`applications` on SQLite fires ON DELETE CASCADE on its children (see the 0008 incident in the README).
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0012_institutions"
down_revision = "0011_synthetic_flag"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inst = op.create_table(
        "institutions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(op.f("ix_institutions_code"), "institutions", ["code"], unique=True)
    default_id = secrets.token_hex(16)
    now = datetime.now(UTC)
    op.bulk_insert(inst, [{
        "id": default_id, "name": "Default institution", "code": "DEFAULT", "is_active": True,
        "created_at": now, "updated_at": now,
    }])
    for table in ("users", "applications"):
        if op.get_bind().dialect.name == "sqlite":
            # Alembic would emit a separate ADD CONSTRAINT, which SQLite lacks; SQLite does accept an inline
            # REFERENCES on ADD COLUMN, and (unlike a batch rebuild) leaves the table and its children untouched. No ON DELETE clause: SQLAlchemy cannot reflect
            # it from an inline column reference, and NO ACTION still refuses to delete an institution that is in use.
            op.execute(sa.text(
                f"ALTER TABLE {table} ADD COLUMN institution_id VARCHAR(32) REFERENCES institutions (id)"
            ))
        else:
            op.add_column(table, sa.Column(
                "institution_id", sa.String(32), sa.ForeignKey("institutions.id"), nullable=True
            ))
        op.create_index(op.f(f"ix_{table}_institution_id"), table, ["institution_id"], unique=False)
        op.execute(sa.text(f"UPDATE {table} SET institution_id = :i").bindparams(i=default_id))


def downgrade() -> None:
    for table in ("applications", "users"):
        op.drop_index(op.f(f"ix_{table}_institution_id"), table_name=table)
        op.drop_column(table, "institution_id")
    op.drop_index(op.f("ix_institutions_code"), table_name="institutions")
    op.drop_table("institutions")
