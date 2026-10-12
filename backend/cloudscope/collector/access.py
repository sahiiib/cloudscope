"""Read-only account access checks, independent of inventory transactions."""

import asyncio
from typing import Protocol, TypedDict

from cloudscope.collector.alibaba import AlibabaProvider
from cloudscope.collector.aws import AWSProvider
from cloudscope.collector.errors import describe_error
from cloudscope.config import AccountConfig


class AccessProvider(Protocol):
    def test_access(self, account: AccountConfig) -> list[str]: ...


class AccessResult(TypedDict, total=False):
    ok: bool
    regions: int
    error: str


class AccountAccess:
    def __init__(self, providers: dict[str, AccessProvider] | None = None, *, timeout: float = 30):
        self.providers: dict[str, AccessProvider] = (
            providers
            if providers is not None
            else {"aws": AWSProvider(), "alibaba": AlibabaProvider()}
        )
        self.timeout = timeout

    async def check(self, account: AccountConfig) -> AccessResult:
        try:
            regions = await asyncio.wait_for(
                asyncio.to_thread(self.providers[account.provider].test_access, account),
                timeout=self.timeout,
            )
            return {"ok": True, "regions": len(regions)}
        except Exception as exc:
            return {"ok": False, "error": f"Region discovery failed: {describe_error(exc)}"}
