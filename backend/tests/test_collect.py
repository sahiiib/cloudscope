from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml
from cryptography.fernet import Fernet
from sqlalchemy import Engine, delete, select, text
from sqlalchemy.orm import Session, sessionmaker
from test_runner import ACCOUNT, FakeProvider
from typer.testing import CliRunner

from cloudscope.cli import app
from cloudscope.db.models import Account, Instance, SyncResult, SyncRun
from cloudscope.db.session import create_session_factory


@pytest.fixture
def collect_env(
    migrated_engine: Engine, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[tuple[FakeProvider, sessionmaker[Session]]]:
    provider = FakeProvider()
    config = tmp_path / "accounts.yaml"
    config.write_text(yaml.safe_dump({"accounts": [ACCOUNT.model_dump()]}))
    monkeypatch.setenv("CLOUDSCOPE_DATABASE_URL", "postgresql+psycopg://localhost/test")
    monkeypatch.setenv("CLOUDSCOPE_SECRET_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("CLOUDSCOPE_ACCOUNTS_FILE", str(config))
    monkeypatch.setattr("cloudscope.cli.create_db_engine", lambda _: migrated_engine)
    monkeypatch.setattr("cloudscope.cli.collect_providers", lambda: {"aws": provider})
    factory = create_session_factory(migrated_engine)
    try:
        yield provider, factory
    finally:
        with factory.begin() as session:
            for model in (SyncResult, Instance, SyncRun, Account):
                session.execute(delete(model))


@pytest.mark.parametrize("status,exit_code", [("success", 0), ("partial", 0), ("failed", 1)])
def test_collect_status_summary_and_trigger(
    collect_env: tuple[FakeProvider, sessionmaker[Session]], status: str, exit_code: int
) -> None:
    provider, factory = collect_env
    if status != "success":
        provider.results["us-east-1"] = RuntimeError("fake-secret")
    if status == "failed":
        provider.results["us-west-2"] = RuntimeError("fake-secret")
    result = CliRunner().invoke(app, ["collect", "--trigger", "schedule"])
    assert result.exit_code == exit_code, result.output
    assert status in result.output and "PROVIDER" in result.output
    assert "us-east-1" in result.output and "us-west-2" in result.output
    assert "fake-secret" not in result.output
    with factory() as session:
        run = session.scalar(select(SyncRun))
        assert run is not None and run.status == status and run.trigger == "schedule"


def test_filters_preserve_unscanned_inventory_and_account_success(
    collect_env: tuple[FakeProvider, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    provider, factory = collect_env
    assert CliRunner().invoke(app, ["collect"]).exit_code == 0
    with factory() as session:
        last_success = session.get_one(Account, ("aws", ACCOUNT.account_id)).last_success_at
    other = ACCOUNT.model_copy(update={"account_id": "222222222222", "name": "other"})
    config = tmp_path / "both.yaml"
    config.write_text(yaml.safe_dump({"accounts": [ACCOUNT.model_dump(), other.model_dump()]}))
    monkeypatch.setenv("CLOUDSCOPE_ACCOUNTS_FILE", str(config))
    provider.calls.clear()
    provider.results["us-east-1"] = []
    result = CliRunner().invoke(
        app, ["collect", "--account", ACCOUNT.account_id, "--region", "us-east-1"]
    )
    assert result.exit_code == 0, result.output
    assert provider.calls == ["us-east-1"]
    with factory() as session:
        assert all(account.enabled for account in session.scalars(select(Account)))
        assert session.get_one(Account, ("aws", ACCOUNT.account_id)).last_success_at == last_success
        rows = {row.region: row for row in session.scalars(select(Instance))}
        assert not rows["us-east-1"].present and rows["us-west-2"].present


@pytest.mark.parametrize("args", [["--account", "unknown"], ["--region", "unknown"]])
def test_unmatched_filter_fails(collect_env: object, args: list[str]) -> None:
    result = CliRunner().invoke(app, ["collect", *args])
    assert result.exit_code == 1


def test_invalid_trigger_rejected_before_collection() -> None:
    assert CliRunner().invoke(app, ["collect", "--trigger", "invalid"]).exit_code == 2


def test_cli_lock_blocks_overlapping_runs(collect_env: object, migrated_engine: Engine) -> None:
    with migrated_engine.connect() as connection:
        connection.execute(text("SELECT pg_advisory_lock(1129530192)"))
        try:
            result = CliRunner().invoke(app, ["collect"])
            assert result.exit_code == 1 and "Another collection" in result.output
        finally:
            connection.execute(text("SELECT pg_advisory_unlock(1129530192)"))
    assert CliRunner().invoke(app, ["collect"]).exit_code == 0


def test_bad_configuration_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLOUDSCOPE_DATABASE_URL", "fake-secret-invalid-url")
    result = CliRunner().invoke(app, ["collect"])
    assert result.exit_code == 1
    assert "fake-secret" not in result.output


@pytest.mark.parametrize(
    "category,expected",
    [
        ("settings", "Configuration invalid: secret_key"),
        ("accounts", "Configuration invalid: accounts.0.provider"),
        ("yaml", "Configuration invalid: accounts"),
        ("missing", "Accounts file not found: "),
        ("database", "Database error: OperationalError"),
        ("filter", "Account filter does not match configuration"),
        ("unknown", "Collection failed: RuntimeError"),
        ("value", "Collection failed: ValueError"),
    ],
)
def test_collect_failure_categories_are_safe(
    collect_env: object,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    category: str,
    expected: str,
) -> None:
    from sqlalchemy.exc import OperationalError

    secret = "fake-secret-in-exception-text"
    args = ["collect"]
    config = tmp_path / "diagnostic-accounts.yaml"
    if category == "settings":
        monkeypatch.setenv("CLOUDSCOPE_SECRET_KEY", secret)
    elif category in {"accounts", "yaml", "missing"}:
        monkeypatch.setenv("CLOUDSCOPE_ACCOUNTS_FILE", str(config))
        if category == "accounts":
            invalid = ACCOUNT.model_dump()
            invalid.update(provider=secret, name=secret)
            config.write_text(yaml.safe_dump({"accounts": [invalid]}))
        elif category == "yaml":
            config.write_text(f"accounts: [{secret}")
        else:
            expected += str(config)
    elif category == "filter":
        args += ["--account", secret]
    else:
        error = (
            OperationalError(secret, {"password": secret}, Exception(secret))
            if category == "database"
            else ValueError(secret)
            if category == "value"
            else RuntimeError(secret)
        )

        def fail_engine(*args: object, **kwargs: object) -> None:
            raise error

        monkeypatch.setattr("cloudscope.cli.create_db_engine", fail_engine)
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 1
    assert result.output.strip() == expected
    assert secret not in result.output
