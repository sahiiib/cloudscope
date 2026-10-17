"""PostgreSQL inventory, collection history, and authentication models."""

from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint("provider IN ('aws', 'alibaba')", name="provider"),
        CheckConstraint("source IN ('file', 'ui')", name="source"),
        CheckConstraint("NOT deleted OR (NOT enabled AND source = 'ui')", name="deleted"),
        CheckConstraint(
            "(connection_mode = 'runtime' AND credential_reference IS NULL) OR "
            "(connection_mode = 'dedicated' AND credential_reference IS NOT NULL "
            "AND source = 'ui' AND role_arn IS NULL AND external_id IS NULL)",
            name="connection",
        ),
    )

    provider: Mapped[str] = mapped_column(Text, primary_key=True)
    account_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    deleted: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cloud_alias: Mapped[str | None] = mapped_column(Text)
    cloud_alias_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(Text, server_default=text("'file'"))
    role_arn: Mapped[str | None] = mapped_column(Text)
    external_id: Mapped[str | None] = mapped_column(Text)
    connection_mode: Mapped[str] = mapped_column(Text, server_default=text("'runtime'"))
    credential_reference: Mapped[str | None] = mapped_column(Text)
    configuration_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    excluded_regions: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    regions: Mapped[str | list[str]] = mapped_column(JSONB, server_default=text("'\"all\"'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), onupdate=lambda: datetime.now(UTC)
    )


class Instance(Base):
    __tablename__ = "instances"
    __table_args__ = (
        ForeignKeyConstraint(
            ["provider", "account_id"], ["accounts.provider", "accounts.account_id"]
        ),
        UniqueConstraint(
            "provider", "account_id", "region", "instance_id", name="uq_instances_identity"
        ),
        CheckConstraint(
            "state IN ('pending', 'running', 'stopping', 'stopped', 'terminated', 'unknown')",
            name="state",
        ),
        Index(
            "ix_instances_search_text",
            "search_text",
            postgresql_using="gin",
            postgresql_ops={"search_text": "gin_trgm_ops"},
        ),
        Index("ix_instances_tags", "tags", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    provider: Mapped[str] = mapped_column(Text, index=True)
    account_id: Mapped[str] = mapped_column(Text, index=True)
    region: Mapped[str] = mapped_column(Text, index=True)
    zone: Mapped[str | None] = mapped_column(Text)
    instance_id: Mapped[str] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str] = mapped_column(Text, index=True)
    provider_state: Mapped[str] = mapped_column(Text)
    instance_type: Mapped[str] = mapped_column(Text)
    private_ips: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"))
    public_ips: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"))
    tags: Mapped[dict[str, str]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    launch_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    vpc_id: Mapped[str | None] = mapped_column(Text)
    subnet_id: Mapped[str | None] = mapped_column(Text)
    key_name: Mapped[str | None] = mapped_column(Text)
    image_id: Mapped[str | None] = mapped_column(Text)
    platform: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, object]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    raw: Mapped[dict[str, object]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    last_observed: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    present: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), index=True)
    search_text: Mapped[str] = mapped_column(
        Text,
        Computed(
            "cloudscope_instance_search_text(name, instance_id, private_ips, public_ips, tags)",
            persisted=True,
        ),
    )


class LoadBalancer(Base):
    __tablename__ = "load_balancers"
    __table_args__ = (
        ForeignKeyConstraint(
            ["provider", "account_id"], ["accounts.provider", "accounts.account_id"]
        ),
        UniqueConstraint(
            "provider",
            "account_id",
            "region",
            "family",
            "load_balancer_id",
            name="uq_load_balancers_identity",
        ),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    provider: Mapped[str] = mapped_column(Text)
    account_id: Mapped[str] = mapped_column(Text)
    region: Mapped[str] = mapped_column(Text)
    family: Mapped[str] = mapped_column(Text)
    load_balancer_id: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(Text)
    scheme: Mapped[str] = mapped_column(Text)
    addresses: Mapped[list[str]] = mapped_column(ARRAY(Text))
    vpc_id: Mapped[str | None] = mapped_column(Text)
    zones: Mapped[list[str]] = mapped_column(ARRAY(Text))
    tags: Mapped[dict[str, str]] = mapped_column(JSONB)
    raw: Mapped[dict[str, object]] = mapped_column(JSONB)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_observed: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    present: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class LoadBalancerScan(Base):
    __tablename__ = "load_balancer_scans"
    __table_args__ = (
        ForeignKeyConstraint(
            ["provider", "account_id"], ["accounts.provider", "accounts.account_id"]
        ),
        CheckConstraint("status IN ('success', 'error')", name="status"),
    )
    provider: Mapped[str] = mapped_column(Text, primary_key=True)
    account_id: Mapped[str] = mapped_column(Text, primary_key=True)
    region: Mapped[str] = mapped_column(Text, primary_key=True)
    family: Mapped[str] = mapped_column(Text, primary_key=True)
    status: Mapped[str] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    last_attempt: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_success: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ElasticIP(Base):
    __tablename__ = "elastic_ips"
    __table_args__ = (
        ForeignKeyConstraint(
            ["provider", "account_id"], ["accounts.provider", "accounts.account_id"]
        ),
        UniqueConstraint(
            "provider",
            "account_id",
            "region",
            "allocation_id",
            name="uq_elastic_ips_identity",
        ),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    provider: Mapped[str] = mapped_column(Text)
    account_id: Mapped[str] = mapped_column(Text)
    region: Mapped[str] = mapped_column(Text)
    allocation_id: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    public_ip: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    associated_type: Mapped[str | None] = mapped_column(Text)
    associated_id: Mapped[str | None] = mapped_column(Text)
    private_ip: Mapped[str | None] = mapped_column(Text)
    network_interface_id: Mapped[str | None] = mapped_column(Text)
    bandwidth: Mapped[str | None] = mapped_column(Text)
    charge_type: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[dict[str, str]] = mapped_column(JSONB)
    raw: Mapped[dict[str, object]] = mapped_column(JSONB)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_observed: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    present: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class NatGateway(Base):
    __tablename__ = "nat_gateways"
    __table_args__ = (
        ForeignKeyConstraint(
            ["provider", "account_id"], ["accounts.provider", "accounts.account_id"]
        ),
        UniqueConstraint(
            "provider",
            "account_id",
            "region",
            "nat_gateway_id",
            name="uq_nat_gateways_identity",
        ),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    provider: Mapped[str] = mapped_column(Text)
    account_id: Mapped[str] = mapped_column(Text)
    region: Mapped[str] = mapped_column(Text)
    nat_gateway_id: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(Text)
    connectivity_type: Mapped[str | None] = mapped_column(Text)
    nat_type: Mapped[str | None] = mapped_column(Text)
    network_type: Mapped[str | None] = mapped_column(Text)
    spec: Mapped[str | None] = mapped_column(Text)
    vpc_id: Mapped[str | None] = mapped_column(Text)
    subnet_id: Mapped[str | None] = mapped_column(Text)
    private_ip: Mapped[str | None] = mapped_column(Text)
    addresses: Mapped[list[dict[str, str | None]]] = mapped_column(JSONB)
    tags: Mapped[dict[str, str]] = mapped_column(JSONB)
    raw: Mapped[dict[str, object]] = mapped_column(JSONB)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_observed: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    present: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class NetworkScan(Base):
    __tablename__ = "network_scans"
    __table_args__ = (
        ForeignKeyConstraint(
            ["provider", "account_id"], ["accounts.provider", "accounts.account_id"]
        ),
        CheckConstraint("resource_type IN ('elastic_ip', 'nat_gateway')", name="resource_type"),
        CheckConstraint("status IN ('success', 'error')", name="status"),
    )
    provider: Mapped[str] = mapped_column(Text, primary_key=True)
    account_id: Mapped[str] = mapped_column(Text, primary_key=True)
    region: Mapped[str] = mapped_column(Text, primary_key=True)
    resource_type: Mapped[str] = mapped_column(Text, primary_key=True)
    status: Mapped[str] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    last_attempt: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_success: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SyncRun(Base):
    __tablename__ = "sync_runs"
    __table_args__ = (
        CheckConstraint("trigger IN ('schedule', 'manual')", name="trigger"),
        CheckConstraint(
            "status IN ('running', 'success', 'partial', 'failed', 'cancelled')", name="status"
        ),
        CheckConstraint("instances_seen >= 0", name="instances_seen"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scope_provider: Mapped[str | None] = mapped_column(Text)
    scope_account_id: Mapped[str | None] = mapped_column(Text)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trigger: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=text("'running'"))
    instances_seen: Mapped[int] = mapped_column(Integer, server_default=text("0"))


class SyncResult(Base):
    __tablename__ = "sync_results"
    __table_args__ = (
        ForeignKeyConstraint(
            ["provider", "account_id"], ["accounts.provider", "accounts.account_id"]
        ),
        CheckConstraint("status IN ('success', 'error')", name="status"),
        CheckConstraint("instances_seen >= 0", name="instances_seen"),
        CheckConstraint("duration_ms >= 0", name="duration_ms"),
    )

    run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("sync_runs.id"), primary_key=True)
    provider: Mapped[str] = mapped_column(Text, primary_key=True)
    account_id: Mapped[str] = mapped_column(Text, primary_key=True)
    region: Mapped[str] = mapped_column(Text, primary_key=True)
    status: Mapped[str] = mapped_column(Text)
    instances_seen: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    error: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int] = mapped_column(Integer)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("failed_logins >= 0", name="failed_logins"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str] = mapped_column(Text, unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    is_admin: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    totp_secret_enc: Mapped[str | None] = mapped_column(Text)
    totp_last_used_step: Mapped[int | None] = mapped_column(BigInteger)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    failed_logins: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserSession(Base):
    __tablename__ = "sessions"
    __table_args__ = (CheckConstraint("mfa_failures >= 0", name="mfa_failures"),)

    mfa_failures: Mapped[int] = mapped_column(Integer, server_default=text("0"))

    id_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    mfa_passed: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    ip: Mapped[str] = mapped_column(Text)
    user_agent: Mapped[str] = mapped_column(Text)
