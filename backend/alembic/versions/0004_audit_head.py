"""Audit chain head row to serialize concurrent appends.

Revision ID: 0004_audit_head
Revises: 0003_applications_documents
Create Date: 2026-10-22

Reviewed manually. Fixes a race found in live testing: two transactions could read the same
"last" audit event and both insert seq N+1 (UNIQUE violation, HTTP 500). Appends now begin by
updating this single row, which takes the database write lock before the previous hash is read.
The head is seeded from the existing chain so verification continues seamlessly.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_audit_head"
down_revision = "0003_applications_documents"
branch_labels = None
depends_on = None

GENESIS = "0" * 64


def upgrade() -> None:
    op.create_table(
        "audit_head",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("last_hash", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_head")),
    )
    bind = op.get_bind()
    last = bind.execute(sa.text("SELECT seq, entry_hash FROM audit_events ORDER BY seq DESC LIMIT 1")).first()
    seq, last_hash = (last[0], last[1]) if last else (0, GENESIS)
    bind.execute(
        sa.text("INSERT INTO audit_head (id, seq, last_hash) VALUES (1, :seq, :h)"), {"seq": seq, "h": last_hash}
    )


def downgrade() -> None:
    op.drop_table("audit_head")
