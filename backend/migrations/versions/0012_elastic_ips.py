"""Elastic IP inventory and per-resource network scan status.

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "elastic_ips",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("account_id", sa.Text(), nullable=False),
        sa.Column("region", sa.Text(), nullable=False),
        sa.Column("allocation_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("public_ip", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("associated_type", sa.Text(), nullable=True),
        sa.Column("associated_id", sa.Text(), nullable=True),
        sa.Column("private_ip", sa.Text(), nullable=True),
        sa.Column("network_interface_id", sa.Text(), nullable=True),
        sa.Column("bandwidth", sa.Text(), nullable=True),
        sa.Column("charge_type", sa.Text(), nullable=True),
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
            "allocation_id",
            name="uq_elastic_ips_identity",
        ),
    )
    op.create_table(
        "network_scans",
        sa.Column("provider", sa.Text(), primary_key=True),
        sa.Column("account_id", sa.Text(), primary_key=True),
        sa.Column("region", sa.Text(), primary_key=True),
        sa.Column("resource_type", sa.Text(), primary_key=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("last_attempt", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_success", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["provider", "account_id"], ["accounts.provider", "accounts.account_id"]
        ),
        sa.CheckConstraint(
            "resource_type IN ('elastic_ip', 'nat_gateway')",
            name=op.f("ck_network_scans_resource_type"),
        ),
        sa.CheckConstraint("status IN ('success', 'error')", name=op.f("ck_network_scans_status")),
    )


def downgrade() -> None:
    op.drop_table("network_scans")
    op.drop_table("elastic_ips")
