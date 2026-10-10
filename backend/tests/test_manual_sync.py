"""Manual collection is serialized across API instances and CLI processes."""

from pathlib import Path
from threading import Event

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from pydantic import SecretStr
from sqlalchemy import Engine, text

from cloudscope.collector.manual import COLLECTION_LOCK_KEY, ManualSync
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
            with pytest.raises(HTTPException) as exc:
                service.start()
            assert exc.value.status_code == 409
        release.set()
        first.close()
        with migrated_engine.connect() as connection:
            assert connection.scalar(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": COLLECTION_LOCK_KEY}
            )
            try:
                with pytest.raises(HTTPException) as exc:
                    second.start()
                assert exc.value.status_code == 409
            finally:
                connection.execute(
                    text("SELECT pg_advisory_unlock(:key)"), {"key": COLLECTION_LOCK_KEY}
                )
    finally:
        release.set()
        first.close()
        second.close()
