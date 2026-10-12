"""Cache cloud account aliases independently of inventory scan success.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("cloud_alias", sa.Text(), nullable=True))
    op.add_column(
        "accounts", sa.Column("cloud_alias_checked_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("accounts", "cloud_alias_checked_at")
    op.drop_column("accounts", "cloud_alias")
