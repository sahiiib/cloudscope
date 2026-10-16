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

    def get_account_alias(self, account: AccountConfig) -> str | None:
        return None

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
        f"account_id={ACCOUNT.account_id}",
        f'region="{region}"',
        f"error={code}",
    ):
        assert field in caplog.text
    assert "fake-secret-message" not in caplog.text


def test_file_and_ui_accounts_reconcile_without_overwriting_ui(
    factory: sessionmaker[Session], caplog: pytest.LogCaptureFixture, tmp_path
) -> None:
    class MixedProvider:
        name = "aws"

        def __init__(self):
            self.scanned = []

        def get_account_alias(self, account):
            return None

        def list_regions(self, account):
            assert isinstance(account.regions, list)
            return account.regions

        def scan(self, account, region):
            self.scanned.append(account)
            return [replace(instance(region), account_id=account.account_id)]

    provider = MixedProvider()
    runner = SyncRunner(factory, {"aws": provider})
    ui = ACCOUNT.model_copy(
        update={
            "account_id": "222222222222",
            "name": "UI account",
            "role_arn": "arn:aws:iam::222222222222:role/test",
            "external_id": "test-external",
            "regions": ["eu-central-1"],
        }
    )
    with factory.begin() as session:
        session.add(Account(**ui.model_dump(), source="ui"))
    assert runner.run([ACCOUNT]).instances_seen == 3
    assert {a.account_id for a in provider.scanned} == {ACCOUNT.account_id, ui.account_id}
    provider.scanned.clear()
    collision = ui.model_copy(update={"name": "file overwrite", "regions": ["us-east-1"]})
    assert runner.run([collision]).instances_seen == 1
    assert provider.scanned == [ui]
    assert "event=account_file_conflict" in caplog.text
    with factory.begin() as session:
        assert not session.get_one(Account, ("aws", ACCOUNT.account_id)).enabled
        account = session.get_one(Account, ("aws", ui.account_id))
        assert account.name == ui.name and account.role_arn == ui.role_arn
        assert account.last_success_at is not None
        account.enabled = False
        snapshot = [(r.id, r.last_observed, r.present) for r in session.scalars(select(Instance))]
    provider.scanned.clear()
    assert runner.run_file(tmp_path / "missing.yaml").status == "success"
    assert provider.scanned == []
    with factory() as session:
        assert [
            (r.id, r.last_observed, r.present) for r in session.scalars(select(Instance))
        ] == snapshot
        assert not session.get_one(Account, ("aws", ui.account_id)).enabled
    with factory.begin() as session:
        session.get_one(Account, ("aws", ui.account_id)).enabled = True
    assert runner.run([], account_id=ui.account_id).instances_seen == 1
    assert provider.scanned == [ui]


def test_file_timestamp_only_changes_when_configuration_changes(factory):
    runner = SyncRunner(factory, {"aws": FakeProvider()}, clock=lambda: NOW)
    runner.run([ACCOUNT])
    runner.clock = lambda: NOW + timedelta(hours=1)
    runner.run([ACCOUNT])
    with factory() as session:
        row = session.get_one(Account, ("aws", ACCOUNT.account_id))
        assert row.updated_at == NOW
        assert row.last_success_at == NOW + timedelta(hours=1)
        assert row.cloud_alias_checked_at == NOW + timedelta(hours=1)
    renamed = ACCOUNT.model_copy(update={"name": "Renamed"})
    runner.run([renamed])
    with factory() as session:
        assert session.get_one(Account, ("aws", ACCOUNT.account_id)).updated_at == NOW + timedelta(
            hours=1
        )
    runner.clock = lambda: NOW + timedelta(hours=2)
    runner.run([])
    runner.clock = lambda: NOW + timedelta(hours=3)
    runner.run([])
    with factory() as session:
        row = session.get_one(Account, ("aws", ACCOUNT.account_id))
        assert not row.enabled and row.updated_at == NOW + timedelta(hours=2)
    runner.run([renamed])
    with factory() as session:
        row = session.get_one(Account, ("aws", ACCOUNT.account_id))
        assert row.enabled and row.updated_at == NOW + timedelta(hours=3)


@pytest.mark.parametrize("cancel_requested,expected", [(False, "failed"), (True, "cancelled")])
def test_stale_running_runs_are_finished_by_next_run(
    factory: sessionmaker[Session], cancel_requested: bool, expected: str
) -> None:
    # A collector killed mid-run (e.g. OOMKilled) leaves its row "running".
    with factory.begin() as session:
        session.add(
            SyncRun(
                trigger="schedule",
                status="running",
                started_at=NOW,
                cancel_requested_at=NOW if cancel_requested else None,
            )
        )
    result = SyncRunner(factory, {"aws": FakeProvider()}).run([ACCOUNT])
    assert result.status == "success"
    with factory() as session:
        runs = session.scalars(select(SyncRun).order_by(SyncRun.id)).all()
        assert [run.status for run in runs] == [expected, "success"]
        assert runs[0].finished_at is not None


def test_unexpected_failure_after_start_marks_run_failed(
    factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("database unavailable")

    runner = SyncRunner(factory, {"aws": FakeProvider()})
    monkeypatch.setattr(runner, "_refresh_alias", broken)
    with pytest.raises(RuntimeError):
        runner.run([ACCOUNT])
    with factory() as session:
        run = session.scalar(select(SyncRun))
        assert run is not None and run.status == "failed" and run.finished_at is not None


def test_scoped_run_isolates_provider_and_other_inventory(factory: sessionmaker[Session]) -> None:
    provider = FakeProvider()
    runner = SyncRunner(factory, {"aws": provider})
    first = runner.run([ACCOUNT])
    with factory.begin() as session:
        session.add(
            Account(
                provider="alibaba",
                account_id=ACCOUNT.account_id,
                name="Other",
                source="ui",
                last_success_at=NOW,
            )
        )
        session.flush()
        session.add(
            Instance(
                provider="alibaba",
                account_id=ACCOUNT.account_id,
                region="us-east-1",
                instance_id="i-other",
                state="running",
                provider_state="running",
                instance_type="test.small",
                private_ips=[],
                public_ips=[],
                tags={},
                details={},
                raw={},
                first_seen=NOW,
                last_observed=NOW,
                present=True,
            )
        )
    provider.calls.clear()
    scoped = runner.run([ACCOUNT], account_id=ACCOUNT.account_id, scope_provider="aws")
    assert scoped.scope_provider == "aws" and scoped.scope_account_id == ACCOUNT.account_id
    assert scoped.status == "success" and first.instances_seen == scoped.instances_seen
    with factory() as session:
        assert session.get_one(Account, ("alibaba", ACCOUNT.account_id)).last_success_at == NOW
        other = session.scalar(select(Instance).where(Instance.provider == "alibaba"))
        assert other is not None and other.present and other.last_observed == NOW
        assert {
            r.provider
            for r in session.scalars(select(SyncResult).where(SyncResult.run_id == scoped.id))
        } == {"aws"}


def test_cancel_from_separate_connection_preserves_unscanned_region(
    factory: sessionmaker[Session],
) -> None:
    provider = FakeProvider()
    runner = SyncRunner(factory, {"aws": provider}, concurrency=1, clock=lambda: NOW)
    runner.run([ACCOUNT])
    original_scan = provider.scan
    provider.calls.clear()

    def scan(account: AccountConfig, region: str) -> list[NormalizedInstance]:
        # A separate session represents an API pod requesting cancellation of a CronJob.
        with factory.begin() as session:
            run = session.scalar(select(SyncRun).where(SyncRun.status == "running"))
            assert run is not None
            run.cancel_requested_at = NOW
        return original_scan(account, region)

    provider.scan = scan  # type: ignore[method-assign]
    runner.clock = lambda: NOW + timedelta(hours=1)
    result = runner.run([ACCOUNT], trigger="schedule")
    assert result.status == "cancelled" and result.finished_at is not None
    assert result.instances_seen == 1 and provider.calls == ["us-east-1"]
    with factory() as session:
        assert session.get_one(Account, ("aws", ACCOUNT.account_id)).last_success_at == NOW
        unscanned = session.scalar(select(Instance).where(Instance.region == "us-west-2"))
        assert unscanned is not None and unscanned.present and unscanned.last_observed == NOW


def test_cancellation_before_next_account_discovery(factory: sessionmaker[Session]) -> None:
    provider = FakeProvider()
    calls = []

    def regions(account: AccountConfig) -> list[str]:
        calls.append(account.account_id)
        with factory.begin() as session:
            run = session.scalar(select(SyncRun).where(SyncRun.status == "running"))
            assert run is not None
            run.cancel_requested_at = NOW
        return ["us-east-1"]

    provider.list_regions = regions  # type: ignore[method-assign]
    result = SyncRunner(factory, {"aws": provider}).run(
        [ACCOUNT, ACCOUNT.model_copy(update={"account_id": "222222222222"})]
    )
    assert result.status == "cancelled"
    assert len(calls) == 1 and provider.calls == []


def test_excluded_regions_not_scanned_and_retired_only_after_success(
    factory: sessionmaker[Session],
) -> None:
    from cloudscope.db.models import LoadBalancer, LoadBalancerScan

    provider = FakeProvider()
    runner = SyncRunner(factory, {"aws": provider}, clock=lambda: NOW)
    runner.run([ACCOUNT])
    with factory.begin() as session:
        session.add(
            LoadBalancer(
                provider="aws",
                account_id=ACCOUNT.account_id,
                region="us-west-2",
                family="elbv2",
                load_balancer_id="test-lb",
                name="test",
                kind="application",
                state="active",
                scheme="internal",
                addresses=[],
                zones=[],
                tags={},
                raw={},
                first_seen=NOW,
                last_observed=NOW,
            )
        )
    with factory.begin() as session:
        for scan_region in ("us-east-1", "us-west-2"):
            session.add(
                LoadBalancerScan(
                    provider="aws",
                    account_id=ACCOUNT.account_id,
                    region=scan_region,
                    family="elbv2",
                    status="error",
                    error="AccessDenied",
                    last_attempt=NOW,
                )
            )
    excluded = ACCOUNT.model_copy(update={"excluded_regions": ["us-west-2"]})
    try:
        provider.results["us-east-1"] = RuntimeError("failed")
        provider.calls.clear()
        assert runner.run([excluded]).status == "failed"
        assert provider.calls == ["us-east-1"]
        with factory() as session:
            assert len(session.scalars(select(LoadBalancerScan)).all()) == 2
            assert session.scalar(select(LoadBalancer.present)) is True
            assert (
                session.scalar(select(Instance.present).where(Instance.region == "us-west-2"))
                is True
            )
        provider.results["us-east-1"] = [instance()]
        result = runner.run([excluded])
        assert result.status == "success"
        with factory() as session:
            assert session.scalars(select(LoadBalancerScan.region)).all() == ["us-east-1"]
            assert session.scalar(select(LoadBalancer.present)) is False
            assert (
                session.scalar(select(Instance.present).where(Instance.region == "us-west-2"))
                is False
            )
            assert session.get_one(Account, ("aws", ACCOUNT.account_id)).excluded_regions == [
                "us-west-2"
            ]
        provider.calls.clear()
        empty = runner.run(
            [ACCOUNT.model_copy(update={"excluded_regions": ["us-east-1", "us-west-2"]})]
        )
        assert empty.status == "failed" and provider.calls == []
        with factory() as session:
            assert "no regions left after exclusions" in session.scalar(
                select(SyncResult.error).where(SyncResult.run_id == empty.id)
            )
    finally:
        with factory.begin() as session:
            session.execute(delete(LoadBalancerScan))
            session.execute(delete(LoadBalancer))
