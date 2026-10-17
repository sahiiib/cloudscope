"""NAT gateway inventory.

Revision ID: 0013
Revises: 0012
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "nat_gateways",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("account_id", sa.Text(), nullable=False),
        sa.Column("region", sa.Text(), nullable=False),
        sa.Column("nat_gateway_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("connectivity_type", sa.Text(), nullable=True),
        sa.Column("nat_type", sa.Text(), nullable=True),
        sa.Column("network_type", sa.Text(), nullable=True),
        sa.Column("spec", sa.Text(), nullable=True),
        sa.Column("vpc_id", sa.Text(), nullable=True),
        sa.Column("subnet_id", sa.Text(), nullable=True),
        sa.Column("private_ip", sa.Text(), nullable=True),
        sa.Column("addresses", postgresql.JSONB(), nullable=False),
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
            "nat_gateway_id",
            name="uq_nat_gateways_identity",
        ),
    )


def downgrade() -> None:
    op.drop_table("nat_gateways")
