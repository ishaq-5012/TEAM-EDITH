"""Persist portal submissions and document-version identity."""

from alembic import op
import sqlalchemy as sa

revision = "0014_portal_intake"
down_revision = "0013_second_approver"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "portal_submissions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("portal_application_id", sa.String(64), nullable=False),
        sa.Column("application_id", sa.String(32), sa.ForeignKey("applications.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("expected_documents", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.UniqueConstraint("portal_application_id", "version"),
    )
    op.create_index("ix_portal_submissions_portal_application_id", "portal_submissions", ["portal_application_id"])
    op.create_table(
        "portal_documents",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("submission_id", sa.String(32), sa.ForeignKey("portal_submissions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("portal_version_id", sa.String(64), nullable=False),
        sa.Column("portal_document_id", sa.String(64), nullable=False),
        sa.Column("document_id", sa.String(32), sa.ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("code", sa.String(60), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.UniqueConstraint("submission_id", "portal_version_id"),
    )


def downgrade() -> None:
    op.drop_table("portal_documents")
    op.drop_index("ix_portal_submissions_portal_application_id", table_name="portal_submissions")
    op.drop_table("portal_submissions")
