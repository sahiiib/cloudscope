"""Initial inventory and authentication schema

Revision ID: 0001
Revises: none
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    # The wrapper is immutable for text arrays / JSON string values. PostgreSQL
    # disallows subqueries and generic array_to_string directly in a generated column.
    op.execute("""
        CREATE FUNCTION cloudscope_instance_search_text(
            instance_name text, instance_identifier text,
            private_addresses text[], public_addresses text[], instance_tags jsonb
        ) RETURNS text
        LANGUAGE sql IMMUTABLE PARALLEL SAFE
        SET search_path = pg_catalog
        AS $function$
            SELECT lower(
                coalesce(instance_name, '') || ' ' ||
                coalesce(instance_identifier, '') || ' ' ||
                coalesce(array_to_string(private_addresses, ' '), '') || ' ' ||
                coalesce(array_to_string(public_addresses, ' '), '') || ' ' ||
                coalesce((
                    SELECT string_agg(key || ' ' || value, ' ' ORDER BY key)
                    FROM jsonb_each_text(instance_tags)
                ), '')
            )
        $function$
    """)
    op.create_table(
        "accounts",
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("account_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("provider IN ('aws', 'alibaba')", name=op.f("ck_accounts_provider")),
        sa.PrimaryKeyConstraint("provider", "account_id", name=op.f("pk_accounts")),
    )
    op.create_table(
        "sync_runs",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'running'"), nullable=False),
        sa.Column("instances_seen", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.CheckConstraint(
            "status IN ('running', 'success', 'partial', 'failed')",
            name=op.f("ck_sync_runs_status"),
        ),
        sa.CheckConstraint("trigger IN ('schedule', 'manual')", name=op.f("ck_sync_runs_trigger")),
        sa.CheckConstraint("instances_seen >= 0", name=op.f("ck_sync_runs_instances_seen")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sync_runs")),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("is_admin", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("totp_secret_enc", sa.Text(), nullable=True),
        sa.Column("mfa_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("failed_logins", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("failed_logins >= 0", name=op.f("ck_users_failed_logins")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("username", name=op.f("uq_users_username")),
    )
    op.create_table(
        "instances",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("account_id", sa.Text(), nullable=False),
        sa.Column("region", sa.Text(), nullable=False),
        sa.Column("zone", sa.Text(), nullable=True),
        sa.Column("instance_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("provider_state", sa.Text(), nullable=False),
        sa.Column("instance_type", sa.Text(), nullable=False),
        sa.Column(
            "private_ips",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "public_ips",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "tags",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("launch_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("vpc_id", sa.Text(), nullable=True),
        sa.Column("subnet_id", sa.Text(), nullable=True),
        sa.Column("key_name", sa.Text(), nullable=True),
        sa.Column("image_id", sa.Text(), nullable=True),
        sa.Column("platform", sa.Text(), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "raw",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "first_seen",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_observed",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("present", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "search_text",
            sa.Text(),
            sa.Computed(
                "cloudscope_instance_search_text(name, instance_id, private_ips, public_ips, tags)",
                persisted=True,
            ),
            nullable=False,
        ),
        sa.CheckConstraint(
            "state IN ('pending', 'running', 'stopping', 'stopped', 'terminated', 'unknown')",
            name=op.f("ck_instances_state"),
        ),
        sa.ForeignKeyConstraint(
            ["provider", "account_id"],
            ["accounts.provider", "accounts.account_id"],
            name=op.f("fk_instances_provider_accounts"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_instances")),
        sa.UniqueConstraint(
            "provider", "account_id", "region", "instance_id", name="uq_instances_identity"
        ),
    )
    op.create_index(op.f("ix_instances_account_id"), "instances", ["account_id"], unique=False)
    op.create_index(op.f("ix_instances_present"), "instances", ["present"], unique=False)
    op.create_index(op.f("ix_instances_provider"), "instances", ["provider"], unique=False)
    op.create_index(op.f("ix_instances_region"), "instances", ["region"], unique=False)
    op.create_index(
        "ix_instances_search_text",
        "instances",
        ["search_text"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"search_text": "gin_trgm_ops"},
    )
    op.create_index(op.f("ix_instances_state"), "instances", ["state"], unique=False)
    op.create_index(
        "ix_instances_tags", "instances", ["tags"], unique=False, postgresql_using="gin"
    )
    op.create_table(
        "sessions",
        sa.Column("id_hash", sa.Text(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("mfa_passed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ip", sa.Text(), nullable=False),
        sa.Column("user_agent", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_sessions_user_id_users")),
        sa.PrimaryKeyConstraint("id_hash", name=op.f("pk_sessions")),
    )
    op.create_table(
        "sync_results",
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("account_id", sa.Text(), nullable=False),
        sa.Column("region", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("instances_seen", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.CheckConstraint("status IN ('success', 'error')", name=op.f("ck_sync_results_status")),
        sa.CheckConstraint("duration_ms >= 0", name=op.f("ck_sync_results_duration_ms")),
        sa.CheckConstraint("instances_seen >= 0", name=op.f("ck_sync_results_instances_seen")),
        sa.ForeignKeyConstraint(
            ["provider", "account_id"],
            ["accounts.provider", "accounts.account_id"],
            name=op.f("fk_sync_results_provider_accounts"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["sync_runs.id"], name=op.f("fk_sync_results_run_id_sync_runs")
        ),
        sa.PrimaryKeyConstraint(
            "run_id", "provider", "account_id", "region", name=op.f("pk_sync_results")
        ),
    )


def downgrade() -> None:
    op.drop_table("sync_results")
    op.drop_table("sessions")
    op.drop_index("ix_instances_tags", table_name="instances", postgresql_using="gin")
    op.drop_index(op.f("ix_instances_state"), table_name="instances")
    op.drop_index(
        "ix_instances_search_text",
        table_name="instances",
        postgresql_using="gin",
        postgresql_ops={"search_text": "gin_trgm_ops"},
    )
    op.drop_index(op.f("ix_instances_region"), table_name="instances")
    op.drop_index(op.f("ix_instances_provider"), table_name="instances")
    op.drop_index(op.f("ix_instances_present"), table_name="instances")
    op.drop_index(op.f("ix_instances_account_id"), table_name="instances")
    op.drop_table("instances")
    op.drop_table("users")
    op.drop_table("sync_runs")
    op.drop_table("accounts")
    op.execute("DROP FUNCTION cloudscope_instance_search_text(text, text, text[], text[], jsonb)")
    # pg_trgm may predate Cloudscope or serve other tables: never drop a shared extension.
