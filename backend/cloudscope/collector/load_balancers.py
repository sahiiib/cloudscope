"""Read-only LB normalization and independently atomic per-family snapshots."""

import logging
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import Text, all_, bindparam, update
from sqlalchemy.dialects.postgresql import ARRAY, insert
from sqlalchemy.orm import Session, sessionmaker

from cloudscope.collector.base import Payload, json_payload, unique
from cloudscope.collector.errors import describe_error
from cloudscope.config import AccountConfig
from cloudscope.db.models import LoadBalancer, LoadBalancerScan

logger = logging.getLogger(__name__)
FAMILIES = {"aws": ("elbv2", "classic"), "alibaba": ("clb", "alb", "nlb")}


class Reader(Protocol):
    def call(self, operation: str, **params: object) -> Payload: ...


@dataclass
class NormalizedLoadBalancer:
    provider: str
    account_id: str
    region: str
    family: str
    load_balancer_id: str
    name: str
    kind: str
    state: str
    scheme: str
    addresses: list[str]
    vpc_id: str | None
    zones: list[str]
    tags: dict[str, str]
    raw: Payload


class LoadBalancerProvider(Protocol):
    def scan_load_balancers(
        self, account: AccountConfig, region: str, family: str
    ) -> list[NormalizedLoadBalancer]: ...


def aws_load_balancers(
    reader: Reader, account: AccountConfig, region: str, family: str
) -> list[NormalizedLoadBalancer]:
    if family not in FAMILIES["aws"]:
        raise ValueError("Unsupported LB family")
    result: list[NormalizedLoadBalancer] = []
    marker: str | None = None
    seen: set[str] = set()
    while True:
        page = reader.call(
            f"{family}_describe_load_balancers", **({"Marker": marker} if marker else {})
        )
        field = "LoadBalancerDescriptions" if family == "classic" else "LoadBalancers"
        rows = page.get(field)
        if not isinstance(rows, list):
            raise ValueError("Malformed LB response")
        for lb in rows:
            classic = family == "classic"
            result.append(
                NormalizedLoadBalancer(
                    provider="aws",
                    account_id=account.account_id,
                    region=region,
                    family=family,
                    load_balancer_id=lb["LoadBalancerName"] if classic else lb["LoadBalancerArn"],
                    name=lb["LoadBalancerName"],
                    kind="classic" if classic else lb.get("Type", "unknown"),
                    state="unknown" if classic else lb.get("State", {}).get("Code", "unknown"),
                    scheme=lb.get("Scheme", "unknown"),
                    addresses=unique([lb.get("DNSName")]),
                    vpc_id=lb.get("VPCId"),
                    zones=unique(
                        lb.get("AvailabilityZones", [])
                        if classic
                        else [zone.get("ZoneName") for zone in lb.get("AvailabilityZones", [])]
                    ),
                    tags={},
                    raw=json_payload(lb),
                )
            )
        marker = page.get("NextMarker")
        if not marker:
            return result
        if marker in seen:
            raise RuntimeError("Repeated LB pagination marker")
        seen.add(marker)


def alibaba_load_balancers(
    reader: Reader, account: AccountConfig, region: str, family: str
) -> list[NormalizedLoadBalancer]:
    if family not in FAMILIES["alibaba"]:
        raise ValueError("Unsupported LB family")
    result: list[NormalizedLoadBalancer] = []
    token: str | None = None
    page_number = 1
    seen: set[str] = set()
    while True:
        params: dict[str, object] = {} if family == "alb" else {"region_id": region}
        if family == "clb":
            params.update(page_number=page_number, page_size=100)
        else:
            params.update(max_results=100)
            if token:
                params["next_token"] = token
        page = reader.call(f"{family}_load_balancers", **params)
        rows = page.get("LoadBalancers")
        if family == "clb":
            if not isinstance(rows, dict):
                raise ValueError("Malformed LB response")
            rows = rows.get("LoadBalancer")
        if not isinstance(rows, list):
            raise ValueError("Malformed LB response")
        for lb in rows:
            addresses = unique(
                [
                    lb.get("DNSName"),
                    lb.get("Address"),
                    *(
                        address.get("Address")
                        for zone in lb.get("ZoneMappings", [])
                        for address in zone.get("LoadBalancerAddresses", [])
                    ),
                ]
            )
            result.append(
                NormalizedLoadBalancer(
                    provider="alibaba",
                    account_id=account.account_id,
                    region=region,
                    family=family,
                    load_balancer_id=lb["LoadBalancerId"],
                    name=lb.get("LoadBalancerName") or lb["LoadBalancerId"],
                    kind=family,
                    state=lb.get("LoadBalancerStatus", "unknown"),
                    scheme={"internet": "internet-facing", "intranet": "internal"}.get(
                        lb.get("AddressType", ""), "unknown"
                    ),
                    addresses=addresses,
                    vpc_id=lb.get("VpcId"),
                    zones=unique(
                        [
                            lb.get("MasterZoneId"),
                            lb.get("SlaveZoneId"),
                            *(zone.get("ZoneId") for zone in lb.get("ZoneMappings", [])),
                        ]
                    ),
                    tags={
                        tag.get("Key", tag.get("TagKey", "")): tag.get(
                            "Value", tag.get("TagValue", "")
                        )
                        for tag in lb.get("Tags", [])
                    },
                    raw=json_payload(lb),
                )
            )
        if family == "clb":
            total = page.get("TotalCount")
            if not rows or (total is not None and len(result) >= total):
                return result
            if total is None and len(rows) < 100:
                return result
            # Duplicate identities are rejected by the collector before any write.
            identities = {lb.load_balancer_id for lb in result}
            if len(identities) != len(result):
                raise RuntimeError("Repeated LB page")
            page_number += 1
        else:
            token = page.get("NextToken")
            if not token:
                return result
            if token in seen:
                raise RuntimeError("Repeated LB pagination token")
            seen.add(token)


class LoadBalancerCollector:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        providers: Mapping[str, LoadBalancerProvider],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.sessions, self.providers, self.clock = sessions, dict(providers), clock

    def scan(self, account: AccountConfig, region: str) -> None:
        for family in FAMILIES[account.provider]:
            identity = {
                "provider": account.provider,
                "account_id": account.account_id,
                "region": region,
                "family": family,
            }
            attempted = self.clock()
            try:
                rows = self.providers[account.provider].scan_load_balancers(account, region, family)
                seen: set[str] = set()
                for row in rows:
                    if (
                        any(getattr(row, key) != value for key, value in identity.items())
                        or not row.load_balancer_id
                        or row.load_balancer_id in seen
                    ):
                        raise ValueError("Invalid LB scan identity")
                    seen.add(row.load_balancer_id)
                with self.sessions.begin() as session:
                    for row in rows:
                        values = asdict(row)
                        statement = insert(LoadBalancer).values(
                            **values, first_seen=attempted, last_observed=attempted, present=True
                        )
                        session.execute(
                            statement.on_conflict_do_update(
                                constraint="uq_load_balancers_identity",
                                set_={
                                    **{key: statement.excluded[key] for key in values},
                                    "last_observed": attempted,
                                    "present": True,
                                },
                            )
                        )
                    session.execute(
                        update(LoadBalancer)
                        .where(
                            *(
                                getattr(LoadBalancer, key) == value
                                for key, value in identity.items()
                            ),
                            LoadBalancer.load_balancer_id
                            != all_(bindparam("seen", list(seen), type_=ARRAY(Text))),
                        )
                        .values(present=False)
                    )
                    status = insert(LoadBalancerScan).values(
                        **identity,
                        status="success",
                        error=None,
                        last_attempt=attempted,
                        last_success=attempted,
                    )
                    session.execute(
                        status.on_conflict_do_update(
                            index_elements=list(identity),
                            set_={
                                "status": "success",
                                "error": None,
                                "last_attempt": attempted,
                                "last_success": attempted,
                            },
                        )
                    )
            except Exception as exc:
                code = describe_error(exc)
                logger.warning(
                    "event=load_balancer_scan_failed provider=%s region=%s family=%s error=%s",
                    account.provider,
                    region,
                    family,
                    code,
                )
                with self.sessions.begin() as session:
                    status = insert(LoadBalancerScan).values(
                        **identity, status="error", error=code, last_attempt=attempted
                    )
                    session.execute(
                        status.on_conflict_do_update(
                            index_elements=list(identity),
                            set_={"status": "error", "error": code, "last_attempt": attempted},
                        )
                    )


def build_load_balancer_collector(
    sessions: sessionmaker[Session], enabled: bool
) -> LoadBalancerCollector | None:
    if not enabled:
        return None
    # Imports stay local to avoid the provider/normalizer dependency cycle.
    from cloudscope.collector.alibaba import AlibabaProvider
    from cloudscope.collector.aws import AWSProvider

    return LoadBalancerCollector(sessions, {"aws": AWSProvider(), "alibaba": AlibabaProvider()})
