"""Foundation: users and append-only audit_events.

Revision ID: 0001_foundation
Revises:
Create Date: 2026-10-22

Reviewed manually. Audit immutability is enforced with database triggers on
SQLite and PostgreSQL in addition to ORM guards.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

import app.db.base

revision = "0001_foundation"
down_revision = None
branch_labels = None
depends_on = None

UTC_DT = app.db.base.UTCDateTime()


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("role", sa.String(40), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("token_version", sa.Integer(), nullable=False),
        sa.Column("failed_login_count", sa.Integer(), nullable=False),
        sa.Column("locked_until", UTC_DT, nullable=True),
        sa.Column("last_login_at", UTC_DT, nullable=True),
        sa.Column("created_at", UTC_DT, nullable=False),
        sa.Column("updated_at", UTC_DT, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("occurred_at", UTC_DT, nullable=False),
        sa.Column("actor_id", sa.String(32), nullable=True),
        sa.Column("actor_email", sa.String(320), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(60), nullable=True),
        sa.Column("entity_id", sa.String(64), nullable=True),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("prev_hash", sa.String(64), nullable=False),
        sa.Column("entry_hash", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
        sa.UniqueConstraint("entry_hash", name=op.f("uq_audit_events_entry_hash")),
    )
    op.create_index(op.f("ix_audit_events_seq"), "audit_events", ["seq"], unique=True)
    op.create_index(op.f("ix_audit_events_action"), "audit_events", ["action"])
    op.create_index(op.f("ix_audit_events_actor_id"), "audit_events", ["actor_id"])
    op.create_index(op.f("ix_audit_events_entity_type"), "audit_events", ["entity_type"])
    op.create_index(op.f("ix_audit_events_entity_id"), "audit_events", ["entity_id"])

    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute(
            "CREATE TRIGGER audit_events_no_update BEFORE UPDATE ON audit_events "
            "BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;"
        )
        op.execute(
            "CREATE TRIGGER audit_events_no_delete BEFORE DELETE ON audit_events "
            "BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;"
        )
    elif dialect == "postgresql":
        op.execute(
            "CREATE FUNCTION audit_events_block() RETURNS trigger AS $$ "
            "BEGIN RAISE EXCEPTION 'audit_events is append-only'; END; $$ LANGUAGE plpgsql;"
        )
        op.execute(
            "CREATE TRIGGER audit_events_no_mutation BEFORE UPDATE OR DELETE ON audit_events "
            "FOR EACH ROW EXECUTE FUNCTION audit_events_block();"
        )


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS audit_events_no_update")
        op.execute("DROP TRIGGER IF EXISTS audit_events_no_delete")
    elif dialect == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS audit_events_no_mutation ON audit_events")
        op.execute("DROP FUNCTION IF EXISTS audit_events_block()")
    op.drop_table("audit_events")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
