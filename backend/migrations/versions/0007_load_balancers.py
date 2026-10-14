"""Independent load-balancer inventory and per-family scan status.

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "load_balancers",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("account_id", sa.Text(), nullable=False),
        sa.Column("region", sa.Text(), nullable=False),
        sa.Column("family", sa.Text(), nullable=False),
        sa.Column("load_balancer_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("scheme", sa.Text(), nullable=False),
        sa.Column("addresses", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("vpc_id", sa.Text(), nullable=True),
        sa.Column("zones", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("tags", postgresql.JSONB(), nullable=False),
        sa.Column("raw", postgresql.JSONB(), nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_observed", sa.DateTime(timezone=True), nullable=False),
        sa.Column("present", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.ForeignKeyConstraint(
            ["provider", "account_id"], ["accounts.provider", "accounts.account_id"]
        ),
        sa.UniqueConstraint(
            "provider",
            "account_id",
            "region",
            "family",
            "load_balancer_id",
            name="uq_load_balancers_identity",
        ),
    )
    op.create_table(
        "load_balancer_scans",
        sa.Column("provider", sa.Text(), primary_key=True),
        sa.Column("account_id", sa.Text(), primary_key=True),
        sa.Column("region", sa.Text(), primary_key=True),
        sa.Column("family", sa.Text(), primary_key=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("last_attempt", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_success", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["provider", "account_id"], ["accounts.provider", "accounts.account_id"]
        ),
        sa.CheckConstraint(
            "status IN ('success', 'error')", name=op.f("ck_load_balancer_scans_status")
        ),
    )


def downgrade() -> None:
    op.drop_table("load_balancer_scans")
    op.drop_table("load_balancers")
