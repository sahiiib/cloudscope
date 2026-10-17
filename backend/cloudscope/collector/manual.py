"""Background collection sharing the CLI's PostgreSQL advisory lock."""

import logging
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock

from sqlalchemy import Engine, text

from cloudscope.collector.alibaba import AlibabaProvider
from cloudscope.collector.aws import AWSProvider
from cloudscope.collector.load_balancers import build_load_balancer_collector
from cloudscope.collector.network import build_network_collector
from cloudscope.collector.runner import SyncRunner
from cloudscope.config import Settings, load_accounts
from cloudscope.db.models import Account
from cloudscope.db.session import create_session_factory

logger = logging.getLogger(__name__)
COLLECTION_LOCK_KEY = 1129530192


class SyncAlreadyRunning(Exception):
    """A collector already owns the collection lock."""


class SyncConfigError(Exception):
    """Collection could not be started; details must remain private."""


class SyncAccountNotFound(Exception):
    """The scoped account does not exist."""


class SyncAccountDisabled(Exception):
    """The scoped account is disabled."""


class ManualSync:
    def __init__(self, engine: Engine, settings: Settings) -> None:
        self.engine, self.settings = engine, settings
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="manual-sync")
        self.guard = Lock()

    def start(self, *, provider: str | None = None, account_id: str | None = None) -> None:
        if not self.guard.acquire(blocking=False):
            raise SyncAlreadyRunning("Another collection is running")
        ready: Future[None] = Future()
        try:
            self.pool.submit(self._run, ready, provider, account_id)
        except Exception:
            self.guard.release()
            raise SyncConfigError("Collection unavailable") from None
        ready.result()

    def _run(self, ready: Future[None], provider: str | None, account_id: str | None) -> None:
        try:
            with self.engine.connect() as connection:
                acquired = connection.scalar(
                    text("SELECT pg_try_advisory_lock(:key)"), {"key": COLLECTION_LOCK_KEY}
                )
                if not acquired:
                    raise SyncAlreadyRunning("Another collection is running")
                try:
                    if provider is not None:
                        with create_session_factory(self.engine)() as session:
                            account = session.get(Account, (provider, account_id))
                            if account is None or account.deleted:
                                raise SyncAccountNotFound()
                            if not account.enabled:
                                raise SyncAccountDisabled()
                    accounts = load_accounts(self.settings.accounts_file)
                    runner = SyncRunner(
                        create_session_factory(self.engine),
                        {"aws": AWSProvider(), "alibaba": AlibabaProvider()},
                        concurrency=self.settings.collect_concurrency,
                        network=build_network_collector(
                            create_session_factory(self.engine), self.settings.network_enabled
                        ),
                        load_balancers=build_load_balancer_collector(
                            create_session_factory(self.engine),
                            self.settings.load_balancers_enabled,
                        ),
                    )
                    ready.set_result(None)
                    runner.run(
                        accounts, trigger="manual", account_id=account_id, scope_provider=provider
                    )
                finally:
                    connection.execute(
                        text("SELECT pg_advisory_unlock(:key)"), {"key": COLLECTION_LOCK_KEY}
                    )
        except Exception as exc:
            if not ready.done():
                ready.set_exception(
                    exc
                    if isinstance(
                        exc, (SyncAlreadyRunning, SyncAccountNotFound, SyncAccountDisabled)
                    )
                    else SyncConfigError("Collection unavailable")
                )
            else:
                logger.error("event=manual_sync_failed error=%s", type(exc).__name__)
        finally:
            self.guard.release()

    def close(self) -> None:
        self.pool.shutdown(wait=True)
