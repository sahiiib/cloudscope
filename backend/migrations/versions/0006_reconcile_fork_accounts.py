"""Reconcile a legacy fork schema without silently discarding active keys.

Revision ID: 0006
Revises: 0005
"""

import logging
import re

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None
logger = logging.getLogger(__name__)
LEGACY = {"connection_config", "credentials_encrypted"}
# Frozen at revision 0005: application models may gain fields in later revisions.
SCHEMA_0005 = {
    "accounts": {
        "provider",
        "account_id",
        "name",
        "enabled",
        "last_success_at",
        "source",
        "role_arn",
        "external_id",
        "regions",
        "created_at",
        "updated_at",
        "cloud_alias",
        "cloud_alias_checked_at",
    },
    "instances": {
        "id",
        "provider",
        "account_id",
        "region",
        "zone",
        "instance_id",
        "name",
        "state",
        "provider_state",
        "instance_type",
        "private_ips",
        "public_ips",
        "tags",
        "launch_time",
        "vpc_id",
        "subnet_id",
        "key_name",
        "image_id",
        "platform",
        "details",
        "raw",
        "first_seen",
        "last_observed",
        "present",
        "search_text",
    },
    "sessions": {
        "id_hash",
        "user_id",
        "mfa_passed",
        "created_at",
        "expires_at",
        "last_seen_at",
        "ip",
        "user_agent",
        "mfa_failures",
    },
    "sync_results": {
        "run_id",
        "provider",
        "account_id",
        "region",
        "status",
        "instances_seen",
        "error",
        "duration_ms",
    },
    "sync_runs": {"id", "started_at", "finished_at", "trigger", "status", "instances_seen"},
    "users": {
        "id",
        "username",
        "password_hash",
        "is_admin",
        "is_active",
        "totp_secret_enc",
        "totp_last_used_step",
        "mfa_enabled",
        "failed_logins",
        "locked_until",
        "created_at",
        "last_login_at",
    },
    "alembic_version": {"version_num"},
}


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
    if set(inspector.get_table_names()) != set(SCHEMA_0005):
        raise RuntimeError("Account reconciliation stopped: unexpected database tables")
    for table, expected_columns in SCHEMA_0005.items():
        actual = {column["name"] for column in inspector.get_columns(table)}
        allowed = expected_columns | (LEGACY if table == "accounts" else set())
        if actual - allowed:
            raise RuntimeError("Account reconciliation stopped: unexpected database columns")
        if table != "accounts" and actual != allowed:
            raise RuntimeError("Account reconciliation stopped: missing database columns")
    columns = {column["name"] for column in inspector.get_columns("accounts")}
    legacy = columns & LEGACY
    count = 0
    if "credentials_encrypted" in columns:
        count = connection.scalar(
            sa.text("SELECT count(*) FROM accounts WHERE credentials_encrypted IS NOT NULL")
        )
        if count:
            # Credential removal requires the separate backed-up operator step.
            raise RuntimeError(
                "Account reconciliation stopped: stored credentials exist; "
                "follow the verified-backup conversion step in docs/fork-reconciliation.md "
                "before upgrading. No keys were discarded."
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
        logger.info("event=reconcile_dropped_credentials count=%s", count)
        for name in sorted(legacy):
            op.drop_column("accounts", name)


def downgrade() -> None:
    # The prior fork schema cannot be reconstructed from upstream metadata.
    # Recovery is a tested backup restore, not an automatic destructive downgrade.
    pass
