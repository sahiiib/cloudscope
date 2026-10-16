"""Read-only account access checks, independent of inventory transactions."""

import asyncio
from typing import Protocol, TypedDict

from cloudscope.collector.alibaba import AlibabaClientFactory, AlibabaProvider
from cloudscope.collector.aws import AWSClientFactory, AWSProvider
from cloudscope.collector.errors import AssumeRoleError, describe_error
from cloudscope.config import AccountConfig, NoRegionsError, included_regions
from cloudscope.credentials import Credentials


class AccessProvider(Protocol):
    def test_access(self, account: AccountConfig) -> list[str]: ...


class AccessResult(TypedDict, total=False):
    ok: bool
    regions: int
    region_ids: list[str]
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
            regions = included_regions(account, regions)
            return {"ok": True, "regions": len(regions), "region_ids": regions}
        except Exception as exc:
            phase = (
                "Assume role failed"
                if isinstance(exc, AssumeRoleError)
                else "Region discovery failed"
            )
            code = (
                "no regions left after exclusions"
                if isinstance(exc, NoRegionsError)
                else describe_error(exc)
            )
            return {"ok": False, "error": f"{phase}: {code}"}


async def test_connection(account: AccountConfig, keys: Credentials | None) -> AccessResult:
    """Request-scoped factories: supplied keys never reach a credential store or shared cache."""
    if keys is None:
        return await AccountAccess().check(account)

    def load_keys(config: AccountConfig) -> Credentials:
        return keys

    providers: dict[str, AccessProvider] = {
        "aws": AWSProvider(
            client_factory=AWSClientFactory(access_test=True, credential_loader=load_keys)
        ),
        "alibaba": AlibabaProvider(
            client_factory=AlibabaClientFactory(access_test=True, credential_loader=load_keys)
        ),
    }
    return await AccountAccess(providers).check(account)
