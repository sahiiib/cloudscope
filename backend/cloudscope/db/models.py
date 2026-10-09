"""PostgreSQL inventory, collection history, and authentication models."""

from datetime import datetime

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
    __table_args__ = (CheckConstraint("provider IN ('aws', 'alibaba')", name="provider"),)

    provider: Mapped[str] = mapped_column(Text, primary_key=True)
    account_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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


class SyncRun(Base):
    __tablename__ = "sync_runs"
    __table_args__ = (
        CheckConstraint("trigger IN ('schedule', 'manual')", name="trigger"),
        CheckConstraint("status IN ('running', 'success', 'partial', 'failed')", name="status"),
        CheckConstraint("instances_seen >= 0", name="instances_seen"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    failed_logins: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserSession(Base):
    __tablename__ = "sessions"

    id_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
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
