"""Background collection sharing the CLI's PostgreSQL advisory lock."""

import logging
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock

from fastapi import HTTPException
from sqlalchemy import Engine, text

from cloudscope.collector.alibaba import AlibabaProvider
from cloudscope.collector.aws import AWSProvider
from cloudscope.collector.runner import SyncRunner
from cloudscope.config import Settings, load_accounts
from cloudscope.db.session import create_session_factory

logger = logging.getLogger(__name__)
COLLECTION_LOCK_KEY = 1129530192


class ManualSync:
    def __init__(self, engine: Engine, settings: Settings) -> None:
        self.engine, self.settings = engine, settings
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="manual-sync")
        self.guard = Lock()

    def start(self) -> None:
        if not self.guard.acquire(blocking=False):
            raise HTTPException(409, "Another collection is running")
        ready: Future[None] = Future()
        try:
            self.pool.submit(self._run, ready)
        except Exception:
            self.guard.release()
            raise HTTPException(503, "Collection unavailable") from None
        ready.result()

    def _run(self, ready: Future[None]) -> None:
        try:
            with self.engine.connect() as connection:
                acquired = connection.scalar(
                    text("SELECT pg_try_advisory_lock(:key)"), {"key": COLLECTION_LOCK_KEY}
                )
                if not acquired:
                    raise HTTPException(409, "Another collection is running")
                try:
                    accounts = load_accounts(self.settings.accounts_file)
                    runner = SyncRunner(
                        create_session_factory(self.engine),
                        {"aws": AWSProvider(), "alibaba": AlibabaProvider()},
                        concurrency=self.settings.collect_concurrency,
                    )
                    ready.set_result(None)
                    runner.run(accounts, trigger="manual")
                finally:
                    connection.execute(
                        text("SELECT pg_advisory_unlock(:key)"), {"key": COLLECTION_LOCK_KEY}
                    )
        except Exception as exc:
            if not ready.done():
                ready.set_exception(
                    exc
                    if isinstance(exc, HTTPException)
                    else HTTPException(503, "Collection unavailable")
                )
            else:
                logger.error("event=manual_sync_failed error=%s", type(exc).__name__)
        finally:
            self.guard.release()

    def close(self) -> None:
        self.pool.shutdown(wait=True)
