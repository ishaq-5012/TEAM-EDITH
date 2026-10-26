"""Server-side sessions, login throttling and the four-role model.

Revision ID: 0002_sessions_and_roles
Revises: 0001_foundation
Create Date: 2026-10-22

Reviewed manually.
- Roles: compliance_officer -> compliance_manager, analyst -> reviewer (the reviewer role
  now also owns case intake). A CHECK constraint then pins the allowed role values.
- users: drops JWT-era columns (token_version, failed_login_count, locked_until). Session
  revocation and the login_attempts table replace them. Adds password_changed_at.
- New tables: user_sessions (hashed tokens only) and login_attempts.

Downgrade restores the columns with defaults and maps roles back. Former analysts come back
as reviewers: that mapping is lossy and cannot be inverted.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

import app.db.base

revision = "0002_sessions_and_roles"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None

UTC_DT = app.db.base.UTCDateTime()
ROLE_CHECK = "role IN ('admin', 'compliance_manager', 'reviewer', 'auditor')"


def upgrade() -> None:
    op.execute("UPDATE users SET role = 'compliance_manager' WHERE role = 'compliance_officer'")
    op.execute("UPDATE users SET role = 'reviewer' WHERE role = 'analyst'")

    with op.batch_alter_table("users") as batch:
        batch.drop_column("token_version")
        batch.drop_column("failed_login_count")
        batch.drop_column("locked_until")
        batch.add_column(sa.Column("password_changed_at", UTC_DT, nullable=True))
        batch.create_check_constraint(op.f("ck_users_role_valid"), ROLE_CHECK)

    op.create_table(
        "user_sessions",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("csrf_hash", sa.String(64), nullable=False),
        sa.Column("created_at", UTC_DT, nullable=False),
        sa.Column("last_seen_at", UTC_DT, nullable=False),
        sa.Column("idle_expires_at", UTC_DT, nullable=False),
        sa.Column("expires_at", UTC_DT, nullable=False),
        sa.Column("revoked_at", UTC_DT, nullable=True),
        sa.Column("revoked_reason", sa.String(60), nullable=True),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(300), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_user_sessions_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_user_sessions_token_hash")),
    )
    op.create_index(op.f("ix_user_sessions_user_id"), "user_sessions", ["user_id"])

    op.create_table(
        "login_attempts",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("succeeded", sa.Boolean(), nullable=False),
        sa.Column("attempted_at", UTC_DT, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_login_attempts")),
    )
    op.create_index("ix_login_attempts_email_at", "login_attempts", ["email", "attempted_at"])
    op.create_index("ix_login_attempts_ip_at", "login_attempts", ["ip_address", "attempted_at"])


def downgrade() -> None:
    op.drop_index("ix_login_attempts_ip_at", table_name="login_attempts")
    op.drop_index("ix_login_attempts_email_at", table_name="login_attempts")
    op.drop_table("login_attempts")
    op.drop_index(op.f("ix_user_sessions_user_id"), table_name="user_sessions")
    op.drop_table("user_sessions")

    with op.batch_alter_table("users") as batch:
        batch.drop_constraint(op.f("ck_users_role_valid"), type_="check")
        batch.drop_column("password_changed_at")
        batch.add_column(sa.Column("locked_until", UTC_DT, nullable=True))
        batch.add_column(sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"))
    op.execute("UPDATE users SET role = 'compliance_officer' WHERE role = 'compliance_manager'")
