"""Read-only Elastic IP snapshots; incomplete responses never retire inventory."""

import logging
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import Text, all_, bindparam, update
from sqlalchemy.dialects.postgresql import ARRAY, insert
from sqlalchemy.orm import Session, sessionmaker

from cloudscope.collector.base import Payload, json_payload
from cloudscope.collector.errors import describe_error, log_account_id
from cloudscope.collector.load_balancers import Reader
from cloudscope.collector.nat_gateways import NormalizedNatGateway
from cloudscope.config import AccountConfig
from cloudscope.db.models import ElasticIP, NatGateway, NetworkScan

logger = logging.getLogger(__name__)


@dataclass
class NormalizedElasticIP:
    provider: str
    account_id: str
    region: str
    allocation_id: str
    public_ip: str
    name: str
    status: str
    associated_type: str | None
    associated_id: str | None
    private_ip: str | None
    network_interface_id: str | None
    bandwidth: str | None
    charge_type: str | None
    tags: dict[str, str]
    raw: Payload


class NetworkProvider(Protocol):
    def scan_nat_gateways(
        self, account: AccountConfig, region: str
    ) -> list[NormalizedNatGateway]: ...

    def scan_elastic_ips(
        self, account: AccountConfig, region: str
    ) -> list[NormalizedElasticIP]: ...


def normalize(row: Payload, account: AccountConfig, region: str) -> NormalizedElasticIP:
    aws = account.provider == "aws"
    if row.get("RegionId") and row["RegionId"] != region:
        raise ValueError("Mismatched Elastic IP region")
    allocation = row["AllocationId"]
    public_ip = row["PublicIp" if aws else "IpAddress"]
    if (
        not isinstance(allocation, str)
        or not allocation
        or not isinstance(public_ip, str)
        or not public_ip
    ):
        raise ValueError("Malformed Elastic IP identity")
    tags = row.get("Tags", [] if aws else {})
    if not aws:
        tags = tags.get("Tag", [])
    tag_map = {tag["Key"]: tag.get("Value", "") for tag in tags}
    if any(
        not isinstance(key, str) or not isinstance(value, str) for key, value in tag_map.items()
    ):
        raise ValueError("Malformed Elastic IP tags")
    associated_type = (
        (
            "instance"
            if row.get("InstanceId")
            else "network_interface"
            if row.get("NetworkInterfaceId")
            else None
        )
        if aws
        else {
            "EcsInstance": "instance",
            "SlbInstance": "load_balancer",
            "Nat": "nat_gateway",
            "NetworkInterface": "network_interface",
        }.get(str(row.get("InstanceType") or ""), row.get("InstanceType") or None)
    )
    return NormalizedElasticIP(
        provider=account.provider,
        account_id=account.account_id,
        region=region,
        allocation_id=allocation,
        public_ip=public_ip,
        name=tag_map.get("Name", "") if aws else row.get("Name") or "",
        status=("associated" if row.get("AssociationId") else "available")
        if aws
        else {"InUse": "associated", "Available": "available"}.get(
            str(row.get("Status") or ""), str(row.get("Status", "unknown")).lower()
        ),
        associated_type=associated_type,
        associated_id=(row.get("InstanceId") or row.get("NetworkInterfaceId"))
        if aws
        else row.get("InstanceId") or None,
        private_ip=row.get("PrivateIpAddress") or None,
        network_interface_id=row.get("NetworkInterfaceId")
        if aws
        else (row.get("InstanceId") if associated_type == "network_interface" else None),
        bandwidth=None
        if aws
        else str(row["Bandwidth"])
        if row.get("Bandwidth") is not None
        else None,
        charge_type=None if aws else row.get("InternetChargeType"),
        tags=tag_map,
        raw=json_payload(row),
    )


def elastic_ips(reader: Reader, account: AccountConfig, region: str) -> list[NormalizedElasticIP]:
    result: list[NormalizedElasticIP] = []
    seen: set[str] = set()
    page_number = 1
    expected_total: int | None = None
    while True:
        aws = account.provider == "aws"
        page = (
            reader.call("describe_addresses")
            if aws
            else reader.call(
                "describe_eip_addresses", region_id=region, page_number=page_number, page_size=100
            )
        )
        rows = page.get("Addresses") if aws else page.get("EipAddresses", {}).get("EipAddress")
        if not isinstance(rows, list):
            raise ValueError("Malformed Elastic IP page")
        for row in rows:
            item = normalize(row, account, region)
            if item.allocation_id in seen:
                raise ValueError("Repeated Elastic IP page")
            seen.add(item.allocation_id)
            result.append(item)
        if aws:
            return result
        if "PageNumber" in page and page["PageNumber"] != page_number:
            raise ValueError("Unexpected Elastic IP page number")
        total = page.get("TotalCount")
        if not isinstance(total, int) or isinstance(total, bool) or total < 0:
            raise ValueError("Missing Elastic IP total")
        if expected_total is not None and total != expected_total:
            raise ValueError("Changing Elastic IP total")
        expected_total = total
        if len(result) == total:
            return result
        if not rows or len(result) > total:
            raise ValueError("Incomplete Elastic IP pages")
        page_number += 1


class NetworkCollector:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        providers: Mapping[str, NetworkProvider],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.sessions, self.providers, self.clock = sessions, dict(providers), clock

    def scan(self, account: AccountConfig, region: str) -> None:
        for resource_type in ("elastic_ip", "nat_gateway"):
            self._scan_resource(account, region, resource_type)

    def _scan_resource(self, account: AccountConfig, region: str, resource_type: str) -> None:
        model = ElasticIP if resource_type == "elastic_ip" else NatGateway
        id_field = "allocation_id" if resource_type == "elastic_ip" else "nat_gateway_id"
        identity = {
            "provider": account.provider,
            "account_id": account.account_id,
            "region": region,
        }
        scan_identity = {**identity, "resource_type": resource_type}
        attempted = self.clock()
        try:
            provider = self.providers[account.provider]
            rows = (
                provider.scan_elastic_ips(account, region)
                if resource_type == "elastic_ip"
                else provider.scan_nat_gateways(account, region)
            )
            seen: set[str] = set()
            for row in rows:
                if (
                    any(getattr(row, key) != value for key, value in identity.items())
                    or not getattr(row, id_field)
                    or getattr(row, id_field) in seen
                ):
                    raise ValueError("Invalid network scan identity")
                seen.add(getattr(row, id_field))
            with self.sessions.begin() as session:
                for row in rows:
                    values = asdict(row)
                    statement = insert(model).values(
                        **values, first_seen=attempted, last_observed=attempted, present=True
                    )
                    session.execute(
                        statement.on_conflict_do_update(
                            constraint=f"uq_{model.__tablename__}_identity",
                            set_={
                                **{key: statement.excluded[key] for key in values},
                                "last_observed": attempted,
                                "present": True,
                            },
                        )
                    )
                session.execute(
                    update(model)
                    .where(
                        *(getattr(model, key) == value for key, value in identity.items()),
                        getattr(model, id_field)
                        != all_(bindparam("seen", list(seen), type_=ARRAY(Text))),
                    )
                    .values(present=False)
                )
                statement = insert(NetworkScan).values(
                    **scan_identity,
                    status="success",
                    error=None,
                    last_attempt=attempted,
                    last_success=attempted,
                )
                session.execute(
                    statement.on_conflict_do_update(
                        index_elements=list(scan_identity),
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
                "event=network_scan_failed provider=%s account_id=%s region=%s "
                "resource_type=%s error=%s",
                account.provider,
                log_account_id(account.account_id),
                region,
                resource_type,
                code,
            )
            with self.sessions.begin() as session:
                statement = insert(NetworkScan).values(
                    **scan_identity, status="error", error=code, last_attempt=attempted
                )
                session.execute(
                    statement.on_conflict_do_update(
                        index_elements=list(scan_identity),
                        set_={"status": "error", "error": code, "last_attempt": attempted},
                    )
                )


def build_network_collector(
    sessions: sessionmaker[Session], enabled: bool
) -> NetworkCollector | None:
    if not enabled:
        return None
    from cloudscope.collector.alibaba import AlibabaProvider
    from cloudscope.collector.aws import AWSProvider

    return NetworkCollector(sessions, {"aws": AWSProvider(), "alibaba": AlibabaProvider()})
