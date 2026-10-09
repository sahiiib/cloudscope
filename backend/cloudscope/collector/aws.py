"""Read-only EC2 collection with injected clients and account-scoped STS sessions."""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Any, Literal, Protocol

import boto3  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]

from cloudscope.collector.base import (
    NormalizedInstance,
    Payload,
    json_payload,
    unique,
    utc_datetime,
)
from cloudscope.config import AccountConfig


class EC2Reader(Protocol):
    def call(self, operation: str, **params: Any) -> Payload: ...


class BotoReader:
    def __init__(self, client: Any) -> None:
        self.client = client

    def call(self, operation: str, **params: Any) -> Payload:
        if operation not in {
            "describe_instances",
            "describe_regions",
            "describe_security_groups",
            "describe_vpcs",
            "describe_subnets",
            "describe_images",
        }:
            raise ValueError("Unsupported read operation")
        result: Payload = getattr(self.client, operation)(**params)
        return result


class AWSClientFactory:
    """Serialize session creation; cache assumed credentials until five minutes before expiry."""

    def __init__(
        self,
        base_session: Any = None,
        session_factory: Callable[..., Any] = boto3.Session,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        discovery_region: str = "us-east-1",
    ) -> None:
        self._base = base_session
        self._session_factory = session_factory
        self._clock = clock
        self._sts_region = discovery_region
        self._cache: dict[tuple[str, str, str | None], tuple[Any, datetime]] = {}
        self._lock = Lock()
        self._config = Config(retries={"mode": "adaptive", "max_attempts": 5})

    def __call__(self, account: AccountConfig, region: str) -> EC2Reader:
        with self._lock:
            if self._base is None:
                self._base = self._session_factory()
            session = self._base
            if account.role_arn:
                key = (account.account_id, account.role_arn, account.external_id)
                cached = self._cache.get(key)
                if cached is None or cached[1] <= self._clock() + timedelta(minutes=5):
                    request = {
                        "RoleArn": account.role_arn,
                        "RoleSessionName": "cloudscope-collector",
                    }
                    if account.external_id:
                        request["ExternalId"] = account.external_id
                    credentials = self._base.client(
                        "sts", region_name=self._sts_region, config=self._config
                    ).assume_role(**request)["Credentials"]
                    session = self._session_factory(
                        aws_access_key_id=credentials["AccessKeyId"],
                        aws_secret_access_key=credentials["SecretAccessKey"],
                        aws_session_token=credentials["SessionToken"],
                    )
                    expiration = utc_datetime(credentials["Expiration"])
                    if expiration is None:
                        raise ValueError("STS response has no expiration")
                    self._cache[key] = (session, expiration)
                else:
                    session = cached[0]
            return BotoReader(session.client("ec2", region_name=region, config=self._config))


def pages(client: EC2Reader, operation: str, **params: Any) -> Iterator[Payload]:
    seen: set[str] = set()
    while True:
        response = client.call(operation, **params)
        yield response
        token = response.get("NextToken")
        if not token:
            return
        if token in seen:
            raise RuntimeError("EC2 returned a repeated pagination token")
        seen.add(token)
        params["NextToken"] = token


def tags(item: Payload) -> dict[str, str]:
    return {tag["Key"]: tag["Value"] for tag in item.get("Tags", [])}


def rules(permissions: list[Payload], direction: str) -> list[Payload]:
    result: list[Payload] = []
    for permission in permissions:
        protocol = permission["IpProtocol"]
        start, end = permission.get("FromPort"), permission.get("ToPort")
        port = (
            "all"
            if protocol == "-1" or start is None
            else (str(start) if start == end else f"{start}-{end}")
        )
        if protocol in {"icmp", "icmpv6", "1", "58"} and start is not None:
            port = f"{start}/{end}"
        for key, field in [
            ("IpRanges", "CidrIp"),
            ("Ipv6Ranges", "CidrIpv6"),
            ("UserIdGroupPairs", "GroupId"),
            ("PrefixListIds", "PrefixListId"),
        ]:
            for peer in permission.get(key, []):
                result.append(
                    {
                        "protocol": protocol,
                        "port_range": port,
                        direction: peer[field],
                        "description": peer.get("Description", ""),
                    }
                )
    return result


class AWSProvider:
    name: Literal["aws"] = "aws"

    def __init__(
        self,
        client_factory: Callable[[AccountConfig, str], EC2Reader] | None = None,
        page_size: int = 1000,
        discovery_region: str = "us-east-1",
    ) -> None:
        if not 5 <= page_size <= 1000:
            raise ValueError("EC2 page_size must be between 5 and 1000")
        self.client_factory = client_factory or AWSClientFactory(discovery_region=discovery_region)
        self.page_size = page_size
        self.discovery_region = discovery_region

    def list_regions(self, account: AccountConfig) -> list[str]:
        self._validate(account)
        if isinstance(account.regions, list):
            return list(account.regions)
        client = self.client_factory(account, self.discovery_region)
        return sorted(
            region["RegionName"]
            for region in client.call("describe_regions", AllRegions=False)["Regions"]
        )

    @staticmethod
    def _validate(account: AccountConfig) -> None:
        if account.provider != "aws":
            raise ValueError("AWSProvider requires an aws account")

    def scan(self, account: AccountConfig, region: str) -> list[NormalizedInstance]:
        self._validate(account)
        client = self.client_factory(account, region)
        instances = [
            item
            for page in pages(client, "describe_instances", MaxResults=self.page_size)
            for reservation in page.get("Reservations", [])
            for item in reservation.get("Instances", [])
        ]
        groups = self._lookup(
            client,
            "security_groups",
            "SecurityGroups",
            "GroupId",
            "group-id",
            {
                group["GroupId"]
                for item in instances
                for group in [
                    *item.get("SecurityGroups", []),
                    *[
                        g
                        for eni in item.get("NetworkInterfaces", [])
                        for g in eni.get("Groups", [])
                    ],
                ]
            },
        )
        vpcs = self._lookup(
            client,
            "vpcs",
            "Vpcs",
            "VpcId",
            "vpc-id",
            {item["VpcId"] for item in instances if item.get("VpcId")},
        )
        subnets = self._lookup(
            client,
            "subnets",
            "Subnets",
            "SubnetId",
            "subnet-id",
            {item["SubnetId"] for item in instances if item.get("SubnetId")},
        )
        images = self._lookup(
            client,
            "images",
            "Images",
            "ImageId",
            "image-id",
            {item["ImageId"] for item in instances if item.get("ImageId")},
        )
        return [
            self._normalize(account, region, item, groups, vpcs, subnets, images)
            for item in instances
        ]

    @staticmethod
    def _lookup(
        client: EC2Reader,
        operation: str,
        result_key: str,
        id_key: str,
        filter_name: str,
        ids: set[str],
    ) -> dict[str, Payload]:
        found: dict[str, Payload] = {}
        ordered = sorted(ids)
        for offset in range(0, len(ordered), 100):
            for page in pages(
                client,
                f"describe_{operation}",
                Filters=[
                    {
                        "Name": filter_name,
                        "Values": ordered[offset : offset + 100],
                    }
                ],
            ):
                for item in page.get(result_key, []):
                    found[item[id_key]] = item
        return found

    @staticmethod
    def _normalize(
        account: AccountConfig,
        region: str,
        item: Payload,
        groups: dict[str, Payload],
        vpcs: dict[str, Payload],
        subnets: dict[str, Payload],
        images: dict[str, Payload],
    ) -> NormalizedInstance:
        enis = item.get("NetworkInterfaces", [])
        private_ips = unique(
            [
                item.get("PrivateIpAddress"),
                *[
                    ip.get("PrivateIpAddress")
                    for eni in enis
                    for ip in [eni, *eni.get("PrivateIpAddresses", [])]
                ],
            ]
        )
        public_ips = unique(
            [
                item.get("PublicIpAddress"),
                *[
                    ip.get("Association", {}).get("PublicIp")
                    for eni in enis
                    for ip in [eni, *eni.get("PrivateIpAddresses", [])]
                ],
            ]
        )
        group_ids = unique(
            [g["GroupId"] for g in item.get("SecurityGroups", [])]
            + [g["GroupId"] for eni in enis for g in eni.get("Groups", [])]
        )
        security_groups = []
        for group_id in group_ids:
            group = groups.get(group_id, {})
            security_groups.append(
                {
                    "id": group_id,
                    "name": group.get("GroupName"),
                    "description": group.get("Description"),
                    "inbound": rules(group.get("IpPermissions", []), "source"),
                    "outbound": rules(group.get("IpPermissionsEgress", []), "destination"),
                }
            )
        vpc = vpcs.get(item.get("VpcId", ""))
        subnet = subnets.get(item.get("SubnetId", ""))
        cpu = item.get("CpuOptions", {})
        state = item["State"]["Name"]
        return NormalizedInstance(
            provider="aws",
            account_id=account.account_id,
            region=region,
            instance_id=item["InstanceId"],
            name=tags(item).get("Name"),
            state={
                "pending": "pending",
                "running": "running",
                "stopping": "stopping",
                "shutting-down": "stopping",
                "stopped": "stopped",
                "terminated": "terminated",
            }.get(state, "unknown"),
            provider_state=state,
            instance_type=item["InstanceType"],
            private_ips=private_ips,
            public_ips=public_ips,
            tags=tags(item),
            launch_time=utc_datetime(item.get("LaunchTime")),
            zone=item.get("Placement", {}).get("AvailabilityZone"),
            vpc_id=item.get("VpcId"),
            subnet_id=item.get("SubnetId"),
            key_name=item.get("KeyName"),
            image_id=item.get("ImageId"),
            platform=item.get("Platform") or "linux",
            details={
                "security_groups": security_groups,
                "vpc": {
                    "id": vpc["VpcId"],
                    "name": tags(vpc).get("Name"),
                    "cidr": vpc.get("CidrBlock"),
                }
                if vpc
                else None,
                "subnet": {
                    "id": subnet["SubnetId"],
                    "name": tags(subnet).get("Name"),
                    "cidr": subnet.get("CidrBlock"),
                }
                if subnet
                else None,
                "network_interfaces": [
                    {
                        "id": eni["NetworkInterfaceId"],
                        "private_ips": unique(
                            [
                                eni.get("PrivateIpAddress"),
                                *[
                                    ip.get("PrivateIpAddress")
                                    for ip in eni.get("PrivateIpAddresses", [])
                                ],
                            ]
                        ),
                        "public_ip": next(
                            (
                                ip["Association"]["PublicIp"]
                                for ip in [eni, *eni.get("PrivateIpAddresses", [])]
                                if ip.get("Association", {}).get("PublicIp")
                            ),
                            None,
                        ),
                        "mac": eni.get("MacAddress"),
                        "security_group_ids": [g["GroupId"] for g in eni.get("Groups", [])],
                    }
                    for eni in enis
                ],
                "key_pair": {"name": item["KeyName"]} if item.get("KeyName") else None,
                "iam_role": item.get("IamInstanceProfile", {}).get("Arn"),
                "image": {
                    "id": item["ImageId"],
                    "name": images.get(item["ImageId"], {}).get("Name"),
                }
                if item.get("ImageId")
                else None,
                "cpu": cpu["CoreCount"] * cpu["ThreadsPerCore"]
                if "CoreCount" in cpu and "ThreadsPerCore" in cpu
                else None,
                "memory_mib": None,
                "monitoring": item.get("Monitoring", {}).get("State"),
            },
            raw=json_payload(item),
        )
