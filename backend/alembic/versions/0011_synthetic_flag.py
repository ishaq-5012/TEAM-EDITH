"""Governance and insights: flag synthetic demo applications.

Revision ID: 0011_synthetic_flag
Revises: 0010_ai_interactions
Create Date: 2026-10-23

Adds applications.is_synthetic (default false), set only by the development-only `seed-demo` command, so dashboards
can label and filter demo data. Uses a plain ADD COLUMN (no batch table rebuild): on SQLite a rebuild of
`applications` would fire ON DELETE CASCADE on its children (see the 0008 incident in the README).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011_synthetic_flag"
down_revision = "0010_ai_interactions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "applications", sa.Column("is_synthetic", sa.Boolean(), server_default=sa.false(), nullable=False)
    )
    op.create_index(op.f("ix_applications_is_synthetic"), "applications", ["is_synthetic"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_applications_is_synthetic"), table_name="applications")
    # SQLite 3.35+ supports DROP COLUMN without a rebuild.
    op.drop_column("applications", "is_synthetic")
