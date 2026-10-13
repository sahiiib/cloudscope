"""Migration checks use an isolated transaction, never the application database."""

import json
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Column, Connection, Engine, Integer, MetaData, Table, inspect, text

from cloudscope.db.models import Base


@pytest.fixture
def hybrid(migrated_engine: Engine, alembic_config: Config) -> Iterator[Connection]:
    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        alembic_config.attributes["connection"] = connection
        try:
            connection.info["fresh_account_constraints"] = {
                constraint["name"]
                for constraint in inspect(connection).get_check_constraints("accounts")
            }
            command.downgrade(alembic_config, "0003")
            connection.execute(text("ALTER TABLE accounts ADD connection_config jsonb"))
            connection.execute(text("ALTER TABLE accounts ADD credentials_encrypted text"))
            connection.execute(text("ALTER TABLE accounts ADD cloud_alias text"))
            connection.execute(text("ALTER TABLE accounts ADD cloud_alias_checked_at timestamptz"))
            command.stamp(alembic_config, "0005")
            yield connection
        finally:
            alembic_config.attributes.pop("connection", None)
            transaction.rollback()


def test_hybrid_reconciles_and_preserves_history(
    hybrid: Connection, alembic_config: Config, caplog: pytest.LogCaptureFixture
) -> None:
    configs = [
        (
            "aws",
            "111111111111",
            {
                "role_arn": "arn:aws:iam::111111111111:role/read",
                "external_id": "test-id",
                "regions": ["us-east-1"],
                "credential_mode": "runtime",
            },
        ),
        (
            "alibaba",
            "2222222222222222",
            {
                "role_arn": "acs:ram::2222222222222222:role/read",
                "regions": ["cn-hangzhou"],
                "external_id": "unsupported-alibaba-external-id",
                "credential_mode": "runtime",
            },
        ),
        ("aws", "444444444444", {"regions": ["us-east-1", "us-east-1"]}),
        (
            "aws",
            "333333333333",
            {
                "role_arn": "arn:aws:iam::111111111111:role/wrong",
                "external_id": "bad secret input!",
                "regions": ["https://private.invalid"],
            },
        ),
    ]
    for provider, identity, config in configs:
        hybrid.execute(
            text(
                "INSERT INTO accounts(provider, account_id, name, connection_config) "
                "VALUES (:provider,:identity,'Test',CAST(:config AS jsonb))"
            ),
            {"provider": provider, "identity": identity, "config": json.dumps(config)},
        )
    hybrid.execute(
        text(
            "INSERT INTO instances(provider,account_id,region,instance_id,state,"
            "provider_state,instance_type) VALUES ('aws','111111111111','us-east-1',"
            "'i-placeholder','running','running','test.small')"
        )
    )
    hybrid.execute(
        text(
            "INSERT INTO users(username,password_hash,totp_secret_enc,mfa_enabled) "
            "VALUES ('placeholder-user','placeholder-hash','placeholder-mfa',true)"
        )
    )
    run = hybrid.scalar(
        text("INSERT INTO sync_runs(trigger,status) VALUES ('manual','success') RETURNING id")
    )
    hybrid.execute(
        text(
            "INSERT INTO sessions(id_hash,user_id,expires_at,ip,user_agent) "
            "SELECT 'placeholder-session-hash',id,'2099-01-01','10.0.0.1','test-agent' FROM users"
        )
    )
    hybrid.execute(
        text(
            "INSERT INTO sync_results(run_id,provider,account_id,region,status,duration_ms) "
            "VALUES (:run,'aws','111111111111','us-east-1','success',1)"
        ),
        {"run": run},
    )
    with caplog.at_level("INFO"):
        command.upgrade(alembic_config, "head")
    assert (
        compare_metadata(
            MigrationContext.configure(hybrid, opts={"compare_server_default": True}), Base.metadata
        )
        == []
    )
    assert {
        constraint["name"] for constraint in inspect(hybrid).get_check_constraints("accounts")
    } == hybrid.info["fresh_account_constraints"]
    rows = (
        hybrid.execute(
            text(
                "SELECT provider,account_id,source,role_arn,external_id,regions "
                "FROM accounts ORDER BY account_id"
            )
        )
        .mappings()
        .all()
    )
    assert all(row["source"] == "file" for row in rows)
    assert rows[0]["role_arn"] == configs[0][2]["role_arn"] and rows[0]["regions"] == ["us-east-1"]
    assert rows[1]["role_arn"] == configs[1][2]["role_arn"] and rows[1]["external_id"] is None
    assert (
        rows[2]["role_arn"] is None
        and rows[2]["external_id"] is None
        and rows[2]["regions"] == "all"
    )
    assert rows[3]["regions"] == "all"
    for table in ("instances", "users", "sessions", "sync_results", "sync_runs"):
        assert hybrid.scalar(text(f"SELECT count(*) FROM {table}")) == 1
    assert hybrid.scalar(text("SELECT totp_secret_enc FROM users")) == "placeholder-mfa"
    assert "event=reconcile_dropped_credentials count=0" in caplog.text
    assert "bad secret input" not in caplog.text and "111111111111" not in caplog.text


def test_normal_upstream_schema_is_unchanged(
    migrated_engine: Engine, alembic_config: Config
) -> None:
    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        alembic_config.attributes["connection"] = connection
        try:
            command.downgrade(alembic_config, "0005")
            before = inspect(connection).get_columns("accounts")
            constraints = inspect(connection).get_check_constraints("accounts")
            command.upgrade(alembic_config, "0006")
            after = inspect(connection).get_columns("accounts")
            assert [(row["name"], str(row["type"]), row["default"]) for row in before] == [
                (row["name"], str(row["type"]), row["default"]) for row in after
            ]
            assert inspect(connection).get_check_constraints("accounts") == constraints
        finally:
            alembic_config.attributes.pop("connection", None)
            transaction.rollback()


def test_stored_keys_abort_before_schema_or_data_changes(
    hybrid: Connection, alembic_config: Config
) -> None:
    hybrid.execute(
        text(
            "INSERT INTO accounts(provider,account_id,name,credentials_encrypted) "
            "VALUES ('aws','111111111111','Test','placeholder-encrypted-key')"
        )
    )
    before = {column["name"] for column in inspect(hybrid).get_columns("accounts")}
    with pytest.raises(RuntimeError, match="stored credentials exist"):
        command.upgrade(alembic_config, "0006")
    assert {column["name"] for column in inspect(hybrid).get_columns("accounts")} == before
    assert (
        hybrid.scalar(text("SELECT credentials_encrypted FROM accounts"))
        == "placeholder-encrypted-key"
    )
    assert hybrid.scalar(text("SELECT version_num FROM alembic_version")) == "0005"


def test_explicit_operator_clear_allows_reconciliation(
    hybrid: Connection, alembic_config: Config, caplog: pytest.LogCaptureFixture
) -> None:
    hybrid.execute(
        text(
            "INSERT INTO accounts(provider,account_id,name,credentials_encrypted) "
            "VALUES ('aws','111111111111','Test','placeholder-encrypted-key')"
        )
    )
    with pytest.raises(RuntimeError, match="stored credentials exist"):
        command.upgrade(alembic_config, "0006")
    cleared = hybrid.execute(
        text(
            "UPDATE accounts SET credentials_encrypted = NULL "
            "WHERE credentials_encrypted IS NOT NULL"
        )
    )
    assert cleared.rowcount == 1
    with caplog.at_level("INFO"):
        command.upgrade(alembic_config, "0006")
    assert hybrid.scalar(text("SELECT count(*) FROM accounts")) == 1
    assert hybrid.scalar(text("SELECT version_num FROM alembic_version")) == "0006"
    assert "credentials_encrypted" not in {
        column["name"] for column in inspect(hybrid).get_columns("accounts")
    }
    assert "event=reconcile_dropped_credentials count=0" in caplog.text
    assert "placeholder-encrypted-key" not in caplog.text


@pytest.mark.parametrize("future_change", ["column", "table"])
def test_migration_uses_frozen_schema_when_models_advance(
    hybrid: Connection,
    alembic_config: Config,
    monkeypatch: pytest.MonkeyPatch,
    future_change: str,
) -> None:
    future_metadata = MetaData()
    for table in Base.metadata.sorted_tables:
        table.to_metadata(future_metadata)
    if future_change == "column":
        future_metadata.tables["instances"].append_column(Column("future_field", Integer))
    else:
        Table("future_table", future_metadata, Column("id", Integer, primary_key=True))
    monkeypatch.setattr(Base, "metadata", future_metadata)
    command.upgrade(alembic_config, "0006")
    assert hybrid.scalar(text("SELECT version_num FROM alembic_version")) == "0006"
    assert "future_table" not in inspect(hybrid).get_table_names()
    assert "future_field" not in {
        column["name"] for column in inspect(hybrid).get_columns("instances")
    }


@pytest.mark.parametrize("unexpected", ["table", "column"])
def test_unknown_schema_aborts(hybrid: Connection, alembic_config: Config, unexpected: str) -> None:
    sql = (
        "CREATE TABLE unexpected_table(id int)"
        if unexpected == "table"
        else "ALTER TABLE accounts ADD unexpected_column text"
    )
    hybrid.execute(text(sql))
    with pytest.raises(RuntimeError, match="unexpected database"):
        command.upgrade(alembic_config, "0006")
    assert hybrid.scalar(text("SELECT version_num FROM alembic_version")) == "0005"
"""Migration checks use an isolated transaction, never the application database."""

import json
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Column, Connection, Engine, Integer, MetaData, Table, inspect, text

from cloudscope.db.models import Base


@pytest.fixture
def hybrid(migrated_engine: Engine, alembic_config: Config) -> Iterator[Connection]:
    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        alembic_config.attributes["connection"] = connection
        try:
            connection.info["fresh_account_constraints"] = {
                constraint["name"]
                for constraint in inspect(connection).get_check_constraints("accounts")
            }
            command.downgrade(alembic_config, "0003")
            connection.execute(text("ALTER TABLE accounts ADD connection_config jsonb"))
            connection.execute(text("ALTER TABLE accounts ADD credentials_encrypted text"))
            connection.execute(text("ALTER TABLE accounts ADD cloud_alias text"))
            connection.execute(text("ALTER TABLE accounts ADD cloud_alias_checked_at timestamptz"))
            command.stamp(alembic_config, "0005")
            yield connection
        finally:
            alembic_config.attributes.pop("connection", None)
            transaction.rollback()


def test_hybrid_reconciles_and_preserves_history(
    hybrid: Connection, alembic_config: Config, caplog: pytest.LogCaptureFixture
) -> None:
    configs = [
        (
            "aws",
            "111111111111",
            {
                "role_arn": "arn:aws:iam::111111111111:role/read",
                "external_id": "test-id",
                "regions": ["us-east-1"],
                "credential_mode": "runtime",
            },
        ),
        (
            "alibaba",
            "2222222222222222",
            {
                "role_arn": "acs:ram::2222222222222222:role/read",
                "regions": ["cn-hangzhou"],
                "external_id": "unsupported-alibaba-external-id",
                "credential_mode": "runtime",
            },
        ),
        ("aws", "444444444444", {"regions": ["us-east-1", "us-east-1"]}),
        (
            "aws",
            "333333333333",
            {
                "role_arn": "arn:aws:iam::111111111111:role/wrong",
                "external_id": "bad secret input!",
                "regions": ["https://private.invalid"],
            },
        ),
    ]
    for provider, identity, config in configs:
        hybrid.execute(
            text(
                "INSERT INTO accounts(provider, account_id, name, connection_config) "
                "VALUES (:provider,:identity,'Test',CAST(:config AS jsonb))"
            ),
            {"provider": provider, "identity": identity, "config": json.dumps(config)},
        )
    hybrid.execute(
        text(
            "INSERT INTO instances(provider,account_id,region,instance_id,state,"
            "provider_state,instance_type) VALUES ('aws','111111111111','us-east-1',"
            "'i-placeholder','running','running','test.small')"
        )
    )
    hybrid.execute(
        text(
            "INSERT INTO users(username,password_hash,totp_secret_enc,mfa_enabled) "
            "VALUES ('placeholder-user','placeholder-hash','placeholder-mfa',true)"
        )
    )
    run = hybrid.scalar(
        text("INSERT INTO sync_runs(trigger,status) VALUES ('manual','success') RETURNING id")
    )
    hybrid.execute(
        text(
            "INSERT INTO sessions(id_hash,user_id,expires_at,ip,user_agent) "
            "SELECT 'placeholder-session-hash',id,'2099-01-01','10.0.0.1','test-agent' FROM users"
        )
    )
    hybrid.execute(
        text(
            "INSERT INTO sync_results(run_id,provider,account_id,region,status,duration_ms) "
            "VALUES (:run,'aws','111111111111','us-east-1','success',1)"
        ),
        {"run": run},
    )
    with caplog.at_level("INFO"):
        command.upgrade(alembic_config, "head")
    assert (
        compare_metadata(
            MigrationContext.configure(hybrid, opts={"compare_server_default": True}), Base.metadata
        )
        == []
    )
    assert {
        constraint["name"] for constraint in inspect(hybrid).get_check_constraints("accounts")
    } == hybrid.info["fresh_account_constraints"]
    rows = (
        hybrid.execute(
            text(
                "SELECT provider,account_id,source,role_arn,external_id,regions "
                "FROM accounts ORDER BY account_id"
            )
        )
        .mappings()
        .all()
    )
    assert all(row["source"] == "file" for row in rows)
    assert rows[0]["role_arn"] == configs[0][2]["role_arn"] and rows[0]["regions"] == ["us-east-1"]
    assert rows[1]["role_arn"] == configs[1][2]["role_arn"] and rows[1]["external_id"] is None
    assert (
        rows[2]["role_arn"] is None
        and rows[2]["external_id"] is None
        and rows[2]["regions"] == "all"
    )
    assert rows[3]["regions"] == "all"
    for table in ("instances", "users", "sessions", "sync_results", "sync_runs"):
        assert hybrid.scalar(text(f"SELECT count(*) FROM {table}")) == 1
    assert hybrid.scalar(text("SELECT totp_secret_enc FROM users")) == "placeholder-mfa"
    assert "event=reconcile_dropped_credentials count=0" in caplog.text
    assert "bad secret input" not in caplog.text and "111111111111" not in caplog.text


def test_normal_upstream_schema_is_unchanged(
    migrated_engine: Engine, alembic_config: Config
) -> None:
    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        alembic_config.attributes["connection"] = connection
        try:
            command.downgrade(alembic_config, "0005")
            before = inspect(connection).get_columns("accounts")
            constraints = inspect(connection).get_check_constraints("accounts")
            command.upgrade(alembic_config, "head")
            after = inspect(connection).get_columns("accounts")
            assert [(row["name"], str(row["type"]), row["default"]) for row in before] == [
                (row["name"], str(row["type"]), row["default"]) for row in after
            ]
            assert inspect(connection).get_check_constraints("accounts") == constraints
        finally:
            alembic_config.attributes.pop("connection", None)
            transaction.rollback()


def test_stored_keys_abort_before_schema_or_data_changes(
    hybrid: Connection, alembic_config: Config
) -> None:
    hybrid.execute(
        text(
            "INSERT INTO accounts(provider,account_id,name,credentials_encrypted) "
            "VALUES ('aws','111111111111','Test','placeholder-encrypted-key')"
        )
    )
    before = {column["name"] for column in inspect(hybrid).get_columns("accounts")}
    with pytest.raises(RuntimeError, match="stored credentials exist"):
        command.upgrade(alembic_config, "head")
    assert {column["name"] for column in inspect(hybrid).get_columns("accounts")} == before
    assert (
        hybrid.scalar(text("SELECT credentials_encrypted FROM accounts"))
        == "placeholder-encrypted-key"
    )
    assert hybrid.scalar(text("SELECT version_num FROM alembic_version")) == "0005"


def test_explicit_operator_clear_allows_reconciliation(
    hybrid: Connection, alembic_config: Config, caplog: pytest.LogCaptureFixture
) -> None:
    hybrid.execute(
        text(
            "INSERT INTO accounts(provider,account_id,name,credentials_encrypted) "
            "VALUES ('aws','111111111111','Test','placeholder-encrypted-key')"
        )
    )
    with pytest.raises(RuntimeError, match="stored credentials exist"):
        command.upgrade(alembic_config, "head")
    cleared = hybrid.execute(
        text(
            "UPDATE accounts SET credentials_encrypted = NULL "
            "WHERE credentials_encrypted IS NOT NULL"
        )
    )
    assert cleared.rowcount == 1
    with caplog.at_level("INFO"):
        command.upgrade(alembic_config, "head")
    assert hybrid.scalar(text("SELECT count(*) FROM accounts")) == 1
    assert hybrid.scalar(text("SELECT version_num FROM alembic_version")) == "0006"
    assert "credentials_encrypted" not in {
        column["name"] for column in inspect(hybrid).get_columns("accounts")
    }
    assert "event=reconcile_dropped_credentials count=0" in caplog.text
    assert "placeholder-encrypted-key" not in caplog.text


@pytest.mark.parametrize("future_change", ["column", "table"])
def test_migration_uses_frozen_schema_when_models_advance(
    hybrid: Connection,
    alembic_config: Config,
    monkeypatch: pytest.MonkeyPatch,
    future_change: str,
) -> None:
    future_metadata = MetaData()
    for table in Base.metadata.sorted_tables:
        table.to_metadata(future_metadata)
    if future_change == "column":
        future_metadata.tables["instances"].append_column(Column("future_field", Integer))
    else:
        Table("future_table", future_metadata, Column("id", Integer, primary_key=True))
    monkeypatch.setattr(Base, "metadata", future_metadata)
    command.upgrade(alembic_config, "head")
    assert hybrid.scalar(text("SELECT version_num FROM alembic_version")) == "0006"
    assert "future_table" not in inspect(hybrid).get_table_names()
    assert "future_field" not in {
        column["name"] for column in inspect(hybrid).get_columns("instances")
    }


@pytest.mark.parametrize("unexpected", ["table", "column"])
def test_unknown_schema_aborts(hybrid: Connection, alembic_config: Config, unexpected: str) -> None:
    sql = (
        "CREATE TABLE unexpected_table(id int)"
        if unexpected == "table"
        else "ALTER TABLE accounts ADD unexpected_column text"
    )
    hybrid.execute(text(sql))
    with pytest.raises(RuntimeError, match="unexpected database"):
        command.upgrade(alembic_config, "head")
    assert hybrid.scalar(text("SELECT version_num FROM alembic_version")) == "0005"
