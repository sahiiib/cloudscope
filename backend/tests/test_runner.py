"""Exercise runner transactions against Postgres using a fake cloud provider."""

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Barrier
from typing import Literal

import pytest
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session, sessionmaker

from cloudscope.collector.base import NormalizedInstance
from cloudscope.collector.runner import SyncRunner
from cloudscope.config import AccountConfig
from cloudscope.db.models import Account, Instance, SyncResult, SyncRun
from cloudscope.db.session import create_session_factory

ACCOUNT = AccountConfig(
    provider="aws", account_id="111111111111", name="test", regions=["us-east-1", "us-west-2"]
)
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def instance(region: str = "us-east-1") -> NormalizedInstance:
    return NormalizedInstance(
        provider="aws",
        account_id=ACCOUNT.account_id,
        region=region,
        instance_id="i-0123456789abcdef0",
        state="running",
        provider_state="running",
        instance_type="t3.micro",
        private_ips=["10.0.0.1"],
        public_ips=[],
        tags={},
        details={},
        raw={},
    )


class FakeProvider:
    name: Literal["aws"] = "aws"

    def __init__(self) -> None:
        self.results: dict[str, list[NormalizedInstance] | Exception] = {
            "us-east-1": [instance()],
            "us-west-2": [instance("us-west-2")],
        }
        self.discovery_error = False
        self.calls: list[str] = []
        self.barrier: Barrier | None = None

    def list_regions(self, account: AccountConfig) -> list[str]:
        if self.discovery_error:
            raise RuntimeError("secret SDK error")
        return list(self.results)

    def scan(self, account: AccountConfig, region: str) -> list[NormalizedInstance]:
        self.calls.append(region)
        if self.barrier:
            self.barrier.wait(timeout=5)
        result = self.results[region]
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture
def factory(migrated_engine: Engine) -> Iterator[sessionmaker[Session]]:
    factory = create_session_factory(migrated_engine)
    try:
        yield factory
    finally:
        with factory.begin() as session:
            for model in (SyncResult, Instance, SyncRun, Account):
                session.execute(delete(model))


def test_idempotent_updates_preserve_identity_and_first_seen(
    factory: sessionmaker[Session],
) -> None:
    provider = FakeProvider()
    runner = SyncRunner(factory, {"aws": provider}, clock=lambda: NOW)
    first = runner.run([ACCOUNT], trigger="schedule")
    with factory() as session:
        original = session.scalar(select(Instance).where(Instance.region == "us-east-1"))
        assert original is not None
        original_id = original.id
    provider.results["us-east-1"] = [replace(instance(), name="renamed", tags={"team": "ops"})]
    runner.clock = lambda: NOW + timedelta(hours=1)
    second = runner.run([ACCOUNT])
    assert first.status == second.status == "success"
    assert first.instances_seen == second.instances_seen == 2
    with factory() as session:
        rows = list(session.scalars(select(Instance)))
        assert len(rows) == 2
        changed = next(row for row in rows if row.region == "us-east-1")
        assert changed.id == original_id
        assert changed.first_seen == NOW
        assert changed.last_observed == NOW + timedelta(hours=1)
        assert changed.name == "renamed" and changed.tags == {"team": "ops"}
        assert changed.present
        assert "renamed" in changed.search_text
        account = session.get_one(Account, ("aws", ACCOUNT.account_id))
        assert account.last_success_at == second.finished_at


def test_failure_preserves_inventory_and_successful_empty_scan_marks_missing(
    factory: sessionmaker[Session], caplog: pytest.LogCaptureFixture
) -> None:
    provider = FakeProvider()
    runner = SyncRunner(factory, {"aws": provider}, clock=lambda: NOW)
    runner.run([ACCOUNT])
    provider.results = {"us-east-1": [], "us-west-2": RuntimeError("secret SDK error")}
    runner.clock = lambda: NOW + timedelta(hours=1)
    result = runner.run([ACCOUNT])
    assert result.status == "partial" and result.instances_seen == 0
    with factory() as session:
        rows = {row.region: row for row in session.scalars(select(Instance))}
        assert not rows["us-east-1"].present and rows["us-east-1"].state == "terminated"
        assert rows["us-west-2"].present and rows["us-west-2"].state == "running"
        assert all(row.last_observed == NOW for row in rows.values())
        assert session.get_one(Account, ("aws", ACCOUNT.account_id)).last_success_at == NOW
        results = list(session.scalars(select(SyncResult).where(SyncResult.run_id == result.id)))
        assert {row.status for row in results} == {"success", "error"}
        assert all(row.duration_ms >= 0 for row in results)
        assert "secret" not in str([row.error for row in results])
    assert "secret" not in caplog.text
    provider.results = {"us-east-1": [instance()], "us-west-2": [instance("us-west-2")]}
    runner.run([ACCOUNT])
    with factory() as session:
        assert all(row.present for row in session.scalars(select(Instance)))


def test_removed_accounts_disabled_and_skipped_then_reenabled(
    factory: sessionmaker[Session],
) -> None:
    provider = FakeProvider()
    runner = SyncRunner(factory, {"aws": provider})
    runner.run([ACCOUNT])
    provider.calls.clear()
    result = runner.run([])
    assert result.status == "success" and result.instances_seen == 0
    assert provider.calls == []
    with factory() as session:
        assert not session.get_one(Account, ("aws", ACCOUNT.account_id)).enabled
        assert len(list(session.scalars(select(Instance)))) == 2
    runner.run([ACCOUNT.model_copy(update={"name": "renamed"})])
    with factory() as session:
        account = session.get_one(Account, ("aws", ACCOUNT.account_id))
        assert account.enabled and account.name == "renamed"


@pytest.mark.parametrize("discovery", [False, True])
def test_total_failure_is_recorded(factory: sessionmaker[Session], discovery: bool) -> None:
    provider = FakeProvider()
    provider.discovery_error = discovery
    provider.results = {"us-east-1": RuntimeError("secret")}
    result = SyncRunner(factory, {"aws": provider}).run([ACCOUNT])
    assert result.status == "failed" and result.finished_at is not None
    with factory() as session:
        row = session.scalar(select(SyncResult))
        assert row is not None and row.status == "error"
        assert row.region == ("*" if discovery else "us-east-1")
        assert session.get_one(Account, ("aws", ACCOUNT.account_id)).last_success_at is None


def test_invalid_payload_rolls_back_entire_region(factory: sessionmaker[Session]) -> None:
    provider = FakeProvider()
    runner = SyncRunner(factory, {"aws": provider})
    runner.run([ACCOUNT])
    provider.results["us-east-1"] = [
        replace(instance(), name="must rollback"),
        replace(instance(), instance_id="i-00000000000000000", state="invalid"),
    ]
    assert runner.run([ACCOUNT]).status == "partial"
    with factory() as session:
        rows = list(session.scalars(select(Instance).where(Instance.region == "us-east-1")))
        assert len(rows) == 1 and rows[0].name is None and rows[0].present


def test_workers_scan_concurrently(factory: sessionmaker[Session]) -> None:
    provider = FakeProvider()
    provider.barrier = Barrier(2)
    assert SyncRunner(factory, {"aws": provider}, concurrency=2).run([ACCOUNT]).status == "success"


def test_wrong_identity_cannot_modify_another_region(factory: sessionmaker[Session]) -> None:
    provider = FakeProvider()
    provider.results["us-east-1"] = [instance("us-west-2")]
    assert SyncRunner(factory, {"aws": provider}).run([ACCOUNT]).status == "partial"
    with factory() as session:
        assert len(list(session.scalars(select(Instance)))) == 1


@pytest.mark.parametrize("discovery", [False, True])
@pytest.mark.parametrize("sdk_error", [False, True])
def test_error_diagnostics_exclude_messages(
    factory: sessionmaker[Session],
    caplog: pytest.LogCaptureFixture,
    discovery: bool,
    sdk_error: bool,
) -> None:
    from botocore.exceptions import ClientError

    class FailingProvider(FakeProvider):
        def list_regions(self, account: AccountConfig) -> list[str]:
            if discovery:
                raise failure
            return ["us-east-1"]

    failure = (
        ClientError(
            {"Error": {"Code": "UnauthorizedOperation", "Message": "fake-secret-message"}},
            "DescribeInstances",
        )
        if sdk_error
        else RuntimeError("fake-secret-message")
    )
    provider = FailingProvider()
    provider.results["us-east-1"] = failure
    run = SyncRunner(factory, {"aws": provider}).run([ACCOUNT])
    code = "UnauthorizedOperation" if sdk_error else "RuntimeError"
    phase = "discovery" if discovery else "scan"
    region = "*" if discovery else "us-east-1"
    with factory() as session:
        result = session.scalar(select(SyncResult).where(SyncResult.run_id == run.id))
        assert result is not None
        assert result.error == f"Region {phase} failed: {code}"
        assert "fake-secret-message" not in result.error
    for field in (
        f"run_id={run.id}",
        f"phase={phase}",
        "provider=aws",
        f'account_id="{ACCOUNT.account_id}"',
        f'region="{region}"',
        f"error={code}",
    ):
        assert field in caplog.text
    assert "fake-secret-message" not in caplog.text
