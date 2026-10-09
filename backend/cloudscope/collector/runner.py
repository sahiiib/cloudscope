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

from sqlalchemy import Text, all_, bindparam, select, update
from sqlalchemy.dialects.postgresql import ARRAY, insert
from sqlalchemy.orm import Session, sessionmaker

from cloudscope.collector.base import Provider
from cloudscope.collector.errors import describe_error
from cloudscope.config import AccountConfig, AccountsConfig, load_accounts
from cloudscope.db.models import Account, Instance, SyncResult, SyncRun

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(UTC)


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
    ) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be positive")
        self.sessions = session_factory
        self.providers = dict(providers)
        self.concurrency = concurrency
        self.clock = clock

    def run_file(
        self, path: str | Path, *, trigger: Literal["schedule", "manual"] = "manual"
    ) -> SyncRun:
        return self.run(load_accounts(path), trigger=trigger)

    def run(
        self,
        accounts: Sequence[AccountConfig],
        *,
        trigger: Literal["schedule", "manual"] = "manual",
    ) -> SyncRun:
        accounts = AccountsConfig(accounts=list(accounts)).accounts
        if trigger not in ("schedule", "manual"):
            raise ValueError("invalid collection trigger")
        with self.sessions.begin() as session:
            session.execute(update(Account).values(enabled=False))
            for account in accounts:
                statement = insert(Account).values(
                    provider=account.provider,
                    account_id=account.account_id,
                    name=account.name,
                    enabled=True,
                )
                session.execute(
                    statement.on_conflict_do_update(
                        index_elements=[Account.provider, Account.account_id],
                        set_={"name": statement.excluded.name, "enabled": True},
                    )
                )
            run = SyncRun(trigger=trigger, status="running", started_at=self.clock())
            session.add(run)
            session.flush()
            run_id = run.id

        jobs: list[tuple[AccountConfig, str]] = []
        for account in accounts:
            started = monotonic()
            try:
                provider = self.providers[account.provider]
                regions = list(dict.fromkeys(provider.list_regions(account)))
                if not regions or any(not region.strip() or region == "*" for region in regions):
                    raise ValueError("no valid regions")
                jobs.extend((account, region) for region in regions)
            except Exception as exc:
                self._error(run_id, account, "*", "Region discovery failed", started, exc)

        with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
            futures = [pool.submit(self._scan, run_id, account, region) for account, region in jobs]
            # Scan failures are recorded by workers. A database outage while recording
            # a result must propagate: it cannot be reported as a successful run.
            try:
                for future in futures:
                    future.result()
            except Exception:
                with self.sessions.begin() as session:
                    session.execute(
                        update(SyncRun)
                        .where(SyncRun.id == run_id)
                        .values(status="failed", finished_at=self.clock())
                    )
                raise

        with self.sessions.begin() as session:
            results = list(session.scalars(select(SyncResult).where(SyncResult.run_id == run_id)))
            failures = sum(result.status == "error" for result in results)
            run = session.get_one(SyncRun, run_id)
            run.status = (
                "success" if failures == 0 else "failed" if failures == len(results) else "partial"
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
                if account_results and all(
                    result.status == "success" for result in account_results
                ):
                    session.execute(
                        update(Account)
                        .where(
                            Account.provider == account.provider,
                            Account.account_id == account.account_id,
                        )
                        .values(last_success_at=run.finished_at)
                    )
            session.flush()
            session.expunge(run)
            return run

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
            json.dumps(account.account_id),
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
