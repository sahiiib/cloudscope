"""Read-only NAT gateway normalization and complete pagination."""

from dataclasses import dataclass

from cloudscope.collector.base import Payload, json_payload
from cloudscope.collector.load_balancers import Reader
from cloudscope.config import AccountConfig


@dataclass
class NormalizedNatGateway:
    provider: str
    account_id: str
    region: str
    nat_gateway_id: str
    name: str
    state: str
    connectivity_type: str | None
    nat_type: str | None
    network_type: str | None
    spec: str | None
    vpc_id: str | None
    subnet_id: str | None
    private_ip: str | None
    addresses: list[dict[str, str | None]]
    tags: dict[str, str]
    raw: Payload


def optional_text(row: Payload, field: str) -> str | None:
    value = row.get(field)
    if value is not None and not isinstance(value, str):
        raise ValueError("Malformed NAT field")
    return value or None


def normalize_nat(row: Payload, account: AccountConfig, region: str) -> NormalizedNatGateway:
    aws = account.provider == "aws"
    identity = optional_text(row, "NatGatewayId")
    state = optional_text(row, "State" if aws else "Status")
    if not identity or not state or (row.get("RegionId") and row["RegionId"] != region):
        raise ValueError("Invalid NAT identity or state")
    tags = row.get("Tags", [] if aws else {}).copy()
    if not aws:
        tags = tags.get("Tag", [])
    if not isinstance(tags, list):
        raise ValueError("Malformed NAT tags")
    tag_map = {
        tag["Key" if aws else "TagKey"]: tag.get("Value" if aws else "TagValue", "") for tag in tags
    }
    if any(not isinstance(k, str) or not isinstance(v, str) for k, v in tag_map.items()):
        raise ValueError("Malformed NAT tags")
    entries = (
        row.get("NatGatewayAddresses", []) if aws else row.get("IpLists", {}).get("IpList", [])
    )
    if not isinstance(entries, list):
        raise ValueError("Malformed NAT addresses")
    addresses = [
        {
            "allocation_id": optional_text(address, "AllocationId"),
            "public_ip": optional_text(address, "PublicIp" if aws else "IpAddress"),
            "private_ip": optional_text(address, "PrivateIp") if aws else None,
            "network_interface_id": optional_text(address, "NetworkInterfaceId") if aws else None,
        }
        for address in entries
    ]
    private = row.get("NatGatewayPrivateInfo") or {}
    return NormalizedNatGateway(
        provider=account.provider,
        account_id=account.account_id,
        region=region,
        nat_gateway_id=identity,
        name=tag_map.get("Name", "") if aws else optional_text(row, "Name") or "",
        state=state,
        connectivity_type=optional_text(row, "ConnectivityType") if aws else None,
        nat_type=None if aws else optional_text(row, "NatType"),
        network_type=None if aws else optional_text(row, "NetworkType"),
        spec=None if aws else optional_text(row, "Spec"),
        vpc_id=optional_text(row, "VpcId"),
        subnet_id=optional_text(row, "SubnetId") if aws else optional_text(private, "VswitchId"),
        private_ip=None if aws else optional_text(private, "PrivateIpAddress"),
        addresses=addresses,
        tags=tag_map,
        raw=json_payload(row),
    )


def nat_gateways(reader: Reader, account: AccountConfig, region: str) -> list[NormalizedNatGateway]:
    result: list[NormalizedNatGateway] = []
    identities: set[str] = set()
    tokens: set[str] = set()
    token: str | None = None
    page_number = 1
    expected_total: int | None = None
    aws = account.provider == "aws"
    while True:
        params: dict[str, object] = (
            ({"NextToken": token} if token else {})
            if aws
            else {"region_id": region, "page_number": page_number, "page_size": 50}
        )
        page = reader.call("describe_nat_gateways", **params)
        rows = page.get("NatGateways")
        if not aws:
            rows = rows.get("NatGateway") if isinstance(rows, dict) else None
        if not isinstance(rows, list):
            raise ValueError("Malformed NAT page")
        for row in rows:
            item = normalize_nat(row, account, region)
            if item.nat_gateway_id in identities:
                raise ValueError("Repeated NAT identity")
            identities.add(item.nat_gateway_id)
            result.append(item)
        if aws:
            token = page.get("NextToken")
            if token is None or token == "":
                return result
            if not isinstance(token, str) or token in tokens:
                raise ValueError("Invalid NAT pagination token")
            tokens.add(token)
        else:
            total = page.get("TotalCount")
            if (
                not isinstance(total, int)
                or isinstance(total, bool)
                or total < 0
                or (expected_total is not None and total != expected_total)
            ):
                raise ValueError("Invalid NAT total")
            if "PageNumber" in page and page["PageNumber"] != page_number:
                raise ValueError("Unexpected NAT page number")
            expected_total = total
            if len(result) == total:
                return result
            if not rows or len(result) > total:
                raise ValueError("Incomplete NAT pages")
            page_number += 1
