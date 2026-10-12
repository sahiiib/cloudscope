"""Store file and admin-managed account configuration.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("source", sa.Text(), nullable=False, server_default="file"))
    op.create_check_constraint("ck_accounts_source", "accounts", "source IN ('file', 'ui')")
    for name in ("role_arn", "external_id"):
        op.add_column("accounts", sa.Column(name, sa.Text(), nullable=True))
    op.add_column(
        "accounts",
        sa.Column(
            "regions",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'\"all\"'::jsonb"),
        ),
    )
    for name in ("created_at", "updated_at"):
        op.add_column(
            "accounts",
            sa.Column(
                name, sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
            ),
        )


def downgrade() -> None:
    op.drop_constraint("ck_accounts_source", "accounts", type_="check")
    for name in ("updated_at", "created_at", "regions", "external_id", "role_arn", "source"):
        op.drop_column("accounts", name)
