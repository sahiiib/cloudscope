"""Read-only account access checks, independent of inventory transactions."""

import asyncio
from typing import Protocol, TypedDict

from cloudscope.collector.alibaba import AlibabaClientFactory, AlibabaProvider
from cloudscope.collector.aws import AWSClientFactory, AWSProvider
from cloudscope.collector.errors import AssumeRoleError, describe_error
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
            else {
                "aws": AWSProvider(client_factory=AWSClientFactory(access_test=True)),
                "alibaba": AlibabaProvider(client_factory=AlibabaClientFactory(access_test=True)),
            }
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
            phase = (
                "Assume role failed"
                if isinstance(exc, AssumeRoleError)
                else "Region discovery failed"
            )
            return {"ok": False, "error": f"{phase}: {describe_error(exc)}"}
