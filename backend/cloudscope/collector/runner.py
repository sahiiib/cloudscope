"""Provider-independent collection with one atomic transaction per region."""

import json
import logging
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Literal

from sqlalchemy import Text, all_, bindparam, or_, select, tuple_, update
from sqlalchemy.dialects.postgresql import ARRAY, insert
from sqlalchemy.orm import Session, sessionmaker

from cloudscope.collector.base import Provider
from cloudscope.collector.errors import describe_error, log_account_id
from cloudscope.collector.load_balancers import LoadBalancerCollector
from cloudscope.config import AccountConfig, AccountsConfig, load_accounts
from cloudscope.db.models import Account, Instance, SyncResult, SyncRun

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(UTC)


class AccountFilterError(ValueError):
    """The requested account ID is absent from the complete configuration."""


class SyncRunner:
    """Share providers across workers, but never share SQLAlchemy sessions.

    The caller supplies the complete configuration on every run: accounts removed
    from it are disabled. SDK adapters own credential caching and retry policy.
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        providers: Mapping[str, Provider],
        *,
        concurrency: int = 8,
        clock: Callable[[], datetime] = utc_now,
        load_balancers: LoadBalancerCollector | None = None,
    ) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be positive")
        self.sessions = session_factory
        self.providers = dict(providers)
        self.concurrency = concurrency
        self.clock = clock
        self.load_balancers = load_balancers

    def run_file(
        self, path: str | Path, *, trigger: Literal["schedule", "manual"] = "manual"
    ) -> SyncRun:
        return self.run(load_accounts(path), trigger=trigger)

    def run(
        self,
        accounts: Sequence[AccountConfig],
        *,
        account_id: str | None = None,
        region: str | None = None,
        trigger: Literal["schedule", "manual"] = "manual",
    ) -> SyncRun:
        accounts = AccountsConfig(accounts=list(accounts)).accounts
        if trigger not in ("schedule", "manual"):
            raise ValueError("invalid collection trigger")
        if region is not None and not region.strip():
            raise ValueError("Region filter cannot be blank")
        with self.sessions.begin() as session:
            session.execute(
                update(Account)
                .where(
                    Account.source == "file",
                    Account.enabled.is_(True),
                    tuple_(Account.provider, Account.account_id).not_in(
                        [(account.provider, account.account_id) for account in accounts]
                    ),
                )
                .values(
                    enabled=False,
                    updated_at=self.clock(),
                    configuration_version=Account.configuration_version + 1,
                )
            )
            for account in accounts:
                statement = insert(Account).values(
                    **account.model_dump(exclude={"connection_mode", "credential_reference"}),
                    source="file",
                    enabled=True,
                    updated_at=self.clock(),
                )
                saved = session.scalar(
                    statement.on_conflict_do_update(
                        index_elements=[Account.provider, Account.account_id],
                        set_={
                            **{
                                key: statement.excluded[key]
                                for key in ("name", "role_arn", "external_id", "regions")
                            },
                            "enabled": True,
                            "updated_at": self.clock(),
                            "configuration_version": Account.configuration_version + 1,
                        },
                        where=(Account.source == "file")
                        & or_(
                            *(
                                getattr(Account, field).is_distinct_from(statement.excluded[field])
                                for field in (
                                    "name",
                                    "role_arn",
                                    "external_id",
                                    "regions",
                                    "enabled",
                                )
                            )
                        ),
                    ).returning(Account.account_id)
                )
                if (
                    saved is None
                    and session.scalar(
                        select(Account.source).where(
                            Account.provider == account.provider,
                            Account.account_id == account.account_id,
                        )
                    )
                    == "ui"
                ):
                    logger.warning(
                        "event=account_file_conflict provider=%s account_id=%s",
                        account.provider,
                        log_account_id(account.account_id),
                    )
            accounts = [
                AccountConfig.model_validate(
                    {key: getattr(row, key) for key in AccountConfig.model_fields}
                )
                for row in session.scalars(select(Account).where(Account.enabled.is_(True)))
            ]
            selected = [
                account
                for account in accounts
                if account_id is None or account.account_id == account_id
            ]
            if account_id is not None and not selected:
                raise AccountFilterError("Account filter does not match configuration")
            # Callers hold the collection advisory lock, so no other run is live. A
            # "running" row here was left by a process that was killed mid-run.
            stale = session.scalars(
                update(SyncRun)
                .where(SyncRun.status == "running")
                .values(status="failed", finished_at=self.clock())
                .returning(SyncRun.id)
            ).all()
            if stale:
                logger.warning("event=stale_runs_failed count=%s", len(stale))
            run = SyncRun(trigger=trigger, status="running", started_at=self.clock())
            session.add(run)
            session.flush()
            run_id = run.id

        try:
            return self._collect(run_id, accounts, selected, region)
        except Exception:
            # A run must never stay "running" after its process gave up on it.
            with self.sessions.begin() as session:
                session.execute(
                    update(SyncRun)
                    .where(SyncRun.id == run_id)
                    .values(status="failed", finished_at=self.clock())
                )
            raise

    def _collect(
        self,
        run_id: int,
        accounts: Sequence[AccountConfig],
        selected: Sequence[AccountConfig],
        region: str | None,
    ) -> SyncRun:
        jobs: list[tuple[AccountConfig, str]] = []
        complete_accounts: set[tuple[str, str]] = set()
        for account in selected:
            self._refresh_alias(account)
            started = monotonic()
            try:
                provider = self.providers[account.provider]
                regions = list(dict.fromkeys(provider.list_regions(account)))
                if not regions or any(not region.strip() or region == "*" for region in regions):
                    raise ValueError("no valid regions")
                selected_regions = [
                    target for target in regions if region is None or target == region
                ]
                if selected_regions == regions:
                    complete_accounts.add((account.provider, account.account_id))
                jobs.extend((account, target) for target in selected_regions)
            except Exception as exc:
                self._error(run_id, account, "*", "Region discovery failed", started, exc)

        with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
            futures = [pool.submit(self._scan, run_id, account, region) for account, region in jobs]
            # Scan failures are recorded by workers. A database outage while recording
            # a result must propagate: run() then marks the run failed.
            for future in futures:
                future.result()

        with self.sessions.begin() as session:
            results = list(session.scalars(select(SyncResult).where(SyncResult.run_id == run_id)))
            failures = sum(result.status == "error" for result in results)
            run = session.get_one(SyncRun, run_id)
            run.status = (
                "failed"
                if not results and region is not None
                else "success"
                if failures == 0
                else "failed"
                if failures == len(results)
                else "partial"
            )
            run.finished_at = self.clock()
            run.instances_seen = sum(result.instances_seen for result in results)
            for account in accounts:
                account_results = [
                    result
                    for result in results
                    if (result.provider, result.account_id)
                    == (account.provider, account.account_id)
                ]
                if (
                    (account.provider, account.account_id) in complete_accounts
                    and account_results
                    and all(result.status == "success" for result in account_results)
                ):
                    session.execute(
                        update(Account)
                        .where(
                            Account.provider == account.provider,
                            Account.account_id == account.account_id,
                        )
                        .values(last_success_at=run.finished_at, updated_at=Account.updated_at)
                    )
            session.flush()
            session.expunge(run)
            return run

    def _refresh_alias(self, account: AccountConfig) -> None:
        try:
            alias = self.providers[account.provider].get_account_alias(account)
        except Exception as exc:
            logger.warning(
                "event=account_alias_failed provider=%s account_id=%s error=%s",
                account.provider,
                log_account_id(account.account_id),
                describe_error(exc),
            )
            return
        with self.sessions.begin() as session:
            session.execute(
                update(Account)
                .where(
                    Account.provider == account.provider, Account.account_id == account.account_id
                )
                .values(
                    cloud_alias=alias,
                    cloud_alias_checked_at=self.clock(),
                    updated_at=Account.updated_at,
                )
            )

    def _scan(self, run_id: int, account: AccountConfig, region: str) -> None:
        started = monotonic()
        try:
            instances = self.providers[account.provider].scan(account, region)
            observed = self.clock()
            seen: set[str] = set()
            for instance in instances:
                if (instance.provider, instance.account_id, instance.region) != (
                    account.provider,
                    account.account_id,
                    region,
                ) or instance.instance_id in seen:
                    raise ValueError("invalid scan identity")
                seen.add(instance.instance_id)
            with self.sessions.begin() as session:
                for instance in instances:
                    values = asdict(instance)
                    statement = insert(Instance).values(
                        **values, first_seen=observed, last_observed=observed, present=True
                    )
                    session.execute(
                        statement.on_conflict_do_update(
                            constraint="uq_instances_identity",
                            set_={
                                **{key: statement.excluded[key] for key in values},
                                "last_observed": observed,
                                "present": True,
                            },
                        )
                    )
                # One array parameter avoids PostgreSQL's parameter limit on large scans.
                session.execute(
                    update(Instance)
                    .where(
                        Instance.provider == account.provider,
                        Instance.account_id == account.account_id,
                        Instance.region == region,
                        Instance.present.is_(True),
                        Instance.instance_id
                        != all_(bindparam("seen", list(seen), type_=ARRAY(Text))),
                    )
                    .values(present=False, state="terminated")
                )
                session.add(
                    SyncResult(
                        run_id=run_id,
                        provider=account.provider,
                        account_id=account.account_id,
                        region=region,
                        status="success",
                        instances_seen=len(instances),
                        duration_ms=int((monotonic() - started) * 1000),
                    )
                )
        except Exception as exc:
            self._error(run_id, account, region, "Region scan failed", started, exc)
        if self.load_balancers is not None:
            try:
                self.load_balancers.scan(account, region)
            except Exception as exc:
                logger.warning(
                    "event=load_balancer_step_failed account_id=%s region=%s error=%s",
                    log_account_id(account.account_id),
                    region,
                    describe_error(exc),
                )

    def _error(
        self,
        run_id: int,
        account: AccountConfig,
        region: str,
        error: str,
        started: float,
        exc: Exception,
    ) -> None:
        # SDK/DB exception text can contain credentials or raw payloads. Persist and
        # log only a diagnostic code/class, without exception tracebacks.
        code = describe_error(exc)
        logger.warning(
            "event=collection_error run_id=%s phase=%s provider=%s "
            "account_id=%s region=%s error=%s",
            run_id,
            "discovery" if region == "*" else "scan",
            account.provider,
            log_account_id(account.account_id),
            json.dumps(region),
            code,
        )
        with self.sessions.begin() as session:
            session.add(
                SyncResult(
                    run_id=run_id,
                    provider=account.provider,
                    account_id=account.account_id,
                    region=region,
                    status="error",
                    instances_seen=0,
                    error=f"{error}: {code}"[:200],
                    duration_ms=int((monotonic() - started) * 1000),
                )
            )
