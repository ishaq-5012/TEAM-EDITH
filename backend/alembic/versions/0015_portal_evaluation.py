"""Track automatic validation for each received portal submission."""

from alembic import op
import sqlalchemy as sa

revision = "0015_portal_evaluation"
down_revision = "0014_portal_intake"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("portal_submissions", sa.Column("validation_state", sa.String(20), nullable=False, server_default="pending"))
    op.add_column("portal_submissions", sa.Column("validation_run_id", sa.String(32), nullable=True))
    op.add_column("portal_submissions", sa.Column("validation_error", sa.String(200), nullable=True))


def downgrade() -> None:
    op.drop_column("portal_submissions", "validation_error")
    op.drop_column("portal_submissions", "validation_run_id")
    op.drop_column("portal_submissions", "validation_state")
