"""Manual collection is serialized across API instances and CLI processes."""

from pathlib import Path
from threading import Event

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import Engine, text

from cloudscope.collector.manual import COLLECTION_LOCK_KEY, ManualSync, SyncAlreadyRunning
from cloudscope.collector.runner import SyncRunner
from cloudscope.config import Settings


def test_manual_sync_lock_and_failure_release(
    migrated_engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "accounts.yaml"
    path.write_text("accounts: []\n")
    settings = Settings(
        database_url=SecretStr("postgresql+psycopg://localhost/test"),
        secret_key=SecretStr(Fernet.generate_key().decode()),
        accounts_file=path,
    )
    entered, release = Event(), Event()

    def run(*args: object, **kwargs: object) -> None:
        entered.set()
        assert release.wait(10)
        raise RuntimeError("private-placeholder")

    monkeypatch.setattr(SyncRunner, "run", run)
    first, second = ManualSync(migrated_engine, settings), ManualSync(migrated_engine, settings)
    try:
        first.start()
        assert entered.wait(5)
        for service in (first, second):
            with pytest.raises(SyncAlreadyRunning):
                service.start()
        release.set()
        first.close()
        with migrated_engine.connect() as connection:
            assert connection.scalar(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": COLLECTION_LOCK_KEY}
            )
            try:
                with pytest.raises(SyncAlreadyRunning):
                    second.start()
            finally:
                connection.execute(
                    text("SELECT pg_advisory_unlock(:key)"), {"key": COLLECTION_LOCK_KEY}
                )
    finally:
        release.set()
        first.close()
        second.close()


def test_scoped_manual_validates_account_under_lock_and_forwards_filter(
    migrated_engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import delete

    from cloudscope.collector.manual import SyncAccountDisabled, SyncAccountNotFound
    from cloudscope.db.models import Account
    from cloudscope.db.session import create_session_factory

    factory = create_session_factory(migrated_engine)
    path = tmp_path / "accounts.yaml"
    path.write_text("accounts: []\n")
    settings = Settings(
        database_url=SecretStr("postgresql+psycopg://localhost/test"),
        secret_key=SecretStr(Fernet.generate_key().decode()),
        accounts_file=path,
    )
    seen = {}
    entered, release = Event(), Event()

    def run(*args: object, **kwargs: object) -> None:
        seen.update(kwargs)
        entered.set()
        assert release.wait(5)

    monkeypatch.setattr(SyncRunner, "run", run)
    service = ManualSync(migrated_engine, settings)
    try:
        with pytest.raises(SyncAccountNotFound):
            service.start(provider="aws", account_id="111111111111")
        with factory.begin() as session:
            session.add(
                Account(
                    provider="aws",
                    account_id="111111111111",
                    name="Test",
                    source="ui",
                    enabled=False,
                )
            )
        with pytest.raises(SyncAccountDisabled):
            service.start(provider="aws", account_id="111111111111")
        with factory.begin() as session:
            session.get_one(Account, ("aws", "111111111111")).enabled = True
        service.start(provider="aws", account_id="111111111111")
        assert entered.wait(5)
        assert seen["account_id"] == "111111111111" and seen["scope_provider"] == "aws"
        with pytest.raises(SyncAlreadyRunning):
            service.start(provider="aws", account_id="111111111111")
    finally:
        release.set()
        service.close()
        with factory.begin() as session:
            session.execute(delete(Account).where(Account.account_id == "111111111111"))
