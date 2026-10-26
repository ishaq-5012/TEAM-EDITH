"""Add a fifth officer role without rebuilding the users table.

Revision ID: 0013_second_approver
Revises: 0012_institutions

SQLite user-table rebuilds can cascade into sessions and other child records.
The nullable override is restricted by the service layer; unknown values fail
closed in the permission map. Existing four-role rows keep identical behavior.
"""

import sqlalchemy as sa
from alembic import op

revision = "0013_second_approver"
down_revision = "0012_institutions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("officer_role", sa.String(40), nullable=True))


def downgrade() -> None:
    # Do not silently downgrade users who already hold the fifth role.
    count = op.get_bind().execute(sa.text("SELECT count(*) FROM users WHERE officer_role IS NOT NULL")).scalar_one()
    if count:
        raise RuntimeError("Reassign second-approver accounts before downgrading 0013")
    op.drop_column("users", "officer_role")
