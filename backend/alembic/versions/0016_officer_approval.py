"""Track reviewer handoff and independent auditor approval."""

from alembic import op
import sqlalchemy as sa

revision = "0016_officer_approval"
down_revision = "0015_portal_evaluation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("applications", sa.Column("review_stage", sa.String(20), nullable=False, server_default="reviewer"))
    op.add_column("applications", sa.Column("reviewer_completed_by_id", sa.String(32), nullable=True))
    op.add_column("applications", sa.Column("reviewer_completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("applications", sa.Column("auditor_id", sa.String(32), nullable=True))
    op.add_column("applications", sa.Column("audited_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("applications", sa.Column("audit_note", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("applications", "audit_note")
    op.drop_column("applications", "audited_at")
    op.drop_column("applications", "auditor_id")
    op.drop_column("applications", "reviewer_completed_at")
    op.drop_column("applications", "reviewer_completed_by_id")
    op.drop_column("applications", "review_stage")
