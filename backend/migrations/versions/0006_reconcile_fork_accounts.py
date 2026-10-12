"""Reconcile a legacy fork schema without silently discarding active keys.

Revision ID: 0006
Revises: 0005
"""

import logging
import re

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from cloudscope.db.models import Base

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None
logger = logging.getLogger(__name__)
LEGACY = {"connection_config", "credentials_encrypted"}


def validated_config(provider: str, account_id: str, config: object) -> dict:
    result = {"role_arn": None, "external_id": None, "regions": "all"}
    if not isinstance(config, dict):
        return result
    digits = 12 if provider == "aws" else 16
    if not re.fullmatch(rf"[0-9]{{{digits}}}", account_id):
        return result
    role = config.get("role_arn")
    prefix = "arn:aws:iam::" if provider == "aws" else "acs:ram::"
    if isinstance(role, str) and re.fullmatch(
        re.escape(prefix + account_id + ":role/") + r"[A-Za-z0-9_+=,.@/-]+", role
    ):
        result["role_arn"] = role
    external = config.get("external_id")
    if (
        provider == "aws"
        and isinstance(external, str)
        and re.fullmatch(r"[\w+=,.@:/-]{2,1224}", external, flags=re.ASCII)
    ):
        result["external_id"] = external
    regions = config.get("regions")
    if (
        isinstance(regions, list)
        and regions
        and all(
            isinstance(item, str) and re.fullmatch(r"[a-z0-9-]{2,32}", item) for item in regions
        )
        and len(set(regions)) == len(regions)
    ):
        result["regions"] = regions
    return result


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    expected = set(Base.metadata.tables) | {"alembic_version"}
    if set(inspector.get_table_names()) != expected:
        raise RuntimeError("Account reconciliation stopped: unexpected database tables")
    for table in Base.metadata.sorted_tables:
        actual = {column["name"] for column in inspector.get_columns(table.name)}
        allowed = set(table.columns.keys()) | (LEGACY if table.name == "accounts" else set())
        if actual - allowed:
            raise RuntimeError("Account reconciliation stopped: unexpected database columns")
        if table.name != "accounts" and actual != allowed:
            raise RuntimeError("Account reconciliation stopped: missing database columns")
    columns = {column["name"] for column in inspector.get_columns("accounts")}
    legacy = columns & LEGACY
    if "credentials_encrypted" in columns:
        count = connection.scalar(
            sa.text("SELECT count(*) FROM accounts WHERE credentials_encrypted IS NOT NULL")
        )
        if count:
            # A revision string alone does not authorize deleting live credentials.
            # Resolve the stored-key design with the owner before shared cutover.
            raise RuntimeError(
                "Account reconciliation stopped: stored credentials exist; "
                "resolve the account access-key design before upgrading. No keys were discarded."
            )
    additions = [
        sa.Column("source", sa.Text(), nullable=False, server_default="file"),
        sa.Column("role_arn", sa.Text(), nullable=True),
        sa.Column("external_id", sa.Text(), nullable=True),
        sa.Column(
            "regions",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'\"all\"'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    ]
    for column in additions:
        if column.name not in columns:
            op.add_column("accounts", column)
    constraints = {item["name"] for item in inspector.get_check_constraints("accounts")}
    # 0004's naming convention expands its explicit name to the doubled form.
    if not constraints & {"ck_accounts_source", "ck_accounts_ck_accounts_source"}:
        op.create_check_constraint("ck_accounts_source", "accounts", "source IN ('file', 'ui')")
    if "connection_config" in legacy:
        table = sa.Table("accounts", sa.MetaData(), autoload_with=connection)
        rows = connection.execute(
            sa.select(table.c.provider, table.c.account_id, table.c.connection_config)
        ).all()
        for provider, account_id, config in rows:
            connection.execute(
                table.update()
                .where(table.c.provider == provider, table.c.account_id == account_id)
                .values(source="file", **validated_config(provider, account_id, config))
            )
        logger.info("event=reconcile_account_config count=%s", len(rows))
    if legacy:
        logger.info("event=reconcile_dropped_credentials count=0")
        for name in sorted(legacy):
            op.drop_column("accounts", name)


def downgrade() -> None:
    # The prior fork schema cannot be reconstructed from upstream metadata.
    # Recovery is a tested backup restore, not an automatic destructive downgrade.
    pass
