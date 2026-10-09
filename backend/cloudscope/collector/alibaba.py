"""Read-only Alibaba ECS/VPC collection through official SDK adapters."""

import os
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Any, Literal, Protocol

from alibabacloud_ecs20140526 import models as ecs_models  # type: ignore[import-untyped]
from alibabacloud_ecs20140526.client import Client as ECSClient  # type: ignore[import-untyped]
from alibabacloud_sts20150401 import models as sts_models  # type: ignore[import-untyped]
from alibabacloud_sts20150401.client import Client as STSClient  # type: ignore[import-untyped]
from alibabacloud_tea_openapi.models import Config  # type: ignore[import-untyped]
from alibabacloud_tea_util.models import RuntimeOptions  # type: ignore[import-untyped]
from alibabacloud_vpc20160428 import models as vpc_models  # type: ignore[import-untyped]
from alibabacloud_vpc20160428.client import Client as VPCClient  # type: ignore[import-untyped]

from cloudscope.collector.base import (
    NormalizedInstance,
    Payload,
    json_payload,
    unique,
    utc_datetime,
)
from cloudscope.config import AccountConfig


class AlibabaReader(Protocol):
    def call(self, operation: str, **params: Any) -> Payload: ...


def sdk_client(service: str, config: Any) -> Any:
    # The generated SDKs have no py.typed marker; keep their dynamic surface here.
    return {"ecs": ECSClient, "vpc": VPCClient, "sts": STSClient}[service](config)


def runtime() -> Any:
    return RuntimeOptions(
        autoretry=True, max_attempts=5, backoff_policy="exponential", backoff_period=1
    )


class SDKReader:
    def __init__(self, ecs: Any, vpc: Any) -> None:
        self.ecs, self.vpc = ecs, vpc

    def call(self, operation: str, **params: Any) -> Payload:
        operations = {
            "describe_instances": (self.ecs, ecs_models.DescribeInstancesRequest),
            "describe_regions": (self.ecs, ecs_models.DescribeRegionsRequest),
            "describe_security_group_attribute": (
                self.ecs,
                ecs_models.DescribeSecurityGroupAttributeRequest,
            ),
            "describe_network_interfaces": (self.ecs, ecs_models.DescribeNetworkInterfacesRequest),
            "describe_vpcs": (self.vpc, vpc_models.DescribeVpcsRequest),
            "describe_vswitches": (self.vpc, vpc_models.DescribeVSwitchesRequest),
        }
        if operation not in operations:
            raise ValueError("Unsupported read operation")
        client, request_type = operations[operation]
        response = getattr(client, operation + "_with_options")(request_type(**params), runtime())
        if response.body is None:
            raise RuntimeError("Alibaba response is missing its body")
        result: Payload = response.body.to_map()
        return result


class AlibabaClientFactory:
    def __init__(
        self,
        builder: Callable[[str, Any], Any] = sdk_client,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.builder = builder
        self.clock = clock
        self._cache: dict[tuple[str, str, str | None], tuple[Payload, datetime]] = {}
        self._lock = Lock()

    def __call__(self, account: AccountConfig, region: str) -> AlibabaReader:
        with self._lock:
            key_id = os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_ID")
            key_secret = os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_SECRET")
            if not key_id or not key_secret:
                raise ValueError("Alibaba base access key environment variables are required")
            credentials = {"AccessKeyId": key_id, "AccessKeySecret": key_secret}
            if account.role_arn:
                cache_key = (account.account_id, account.role_arn, account.external_id)
                cached = self._cache.get(cache_key)
                if cached is None or cached[1] <= self.clock() + timedelta(minutes=5):
                    sts = self.builder(
                        "sts",
                        Config(
                            access_key_id=key_id,
                            access_key_secret=key_secret,
                            endpoint="sts.aliyuncs.com",
                        ),
                    )
                    response = sts.assume_role_with_options(
                        sts_models.AssumeRoleRequest(
                            role_arn=account.role_arn,
                            role_session_name="cloudscope-collector",
                            duration_seconds=3600,
                            external_id=account.external_id,
                        ),
                        runtime(),
                    )
                    credentials = response.body.to_map()["Credentials"]
                    expiration = utc_datetime(credentials.get("Expiration"))
                    if expiration is None:
                        raise ValueError("STS response has no expiration")
                    self._cache[cache_key] = (credentials, expiration)
                else:
                    credentials = cached[0]

            def config(service: str) -> Any:
                return Config(
                    access_key_id=credentials["AccessKeyId"],
                    access_key_secret=credentials["AccessKeySecret"],
                    security_token=credentials.get("SecurityToken"),
                    region_id=region,
                    endpoint=f"{service}.{region}.aliyuncs.com",
                )

            return SDKReader(self.builder("ecs", config("ecs")), self.builder("vpc", config("vpc")))


def pages(client: AlibabaReader, operation: str, **params: Any) -> Iterator[Payload]:
    seen: set[str] = set()
    while True:
        page = client.call(operation, **params)
        yield page
        token = page.get("NextToken")
        if not token:
            return
        if token in seen:
            raise RuntimeError("Alibaba returned a repeated pagination token")
        seen.add(token)
        params["next_token"] = token


def eni_private_ips(eni: Payload) -> list[str]:
    return unique(
        [
            eni.get("PrimaryIpAddress"),
            eni.get("PrivateIpAddress"),
            *[
                ip.get("PrivateIpAddress")
                for ip in eni.get("PrivateIpSets", {}).get("PrivateIpSet", [])
            ],
        ]
    )


def eni_public_ips(eni: Payload) -> list[str]:
    return unique(
        [
            entry.get("AssociatedPublicIp", {}).get("PublicIpAddress")
            for entry in [eni, *eni.get("PrivateIpSets", {}).get("PrivateIpSet", [])]
        ]
    )


def security_group(client: AlibabaReader, region: str, group_id: str) -> Payload:
    result: Payload = {
        "id": group_id,
        "name": None,
        "description": None,
        "inbound": [],
        "outbound": [],
    }
    for page in pages(
        client,
        "describe_security_group_attribute",
        region_id=region,
        security_group_id=group_id,
        direction="all",
        max_results=100,
    ):
        result["name"] = page.get("SecurityGroupName", result["name"])
        result["description"] = page.get("Description", result["description"])
        for permission in page.get("Permissions", {}).get("Permission", []):
            direction = permission["Direction"]
            if direction not in {"ingress", "egress"}:
                raise ValueError("Unknown Alibaba security rule direction")
            inbound = direction == "ingress"
            prefix = "Source" if inbound else "Dest"
            peers = unique(
                [
                    permission.get(prefix + "CidrIp"),
                    permission.get("Ipv6" + prefix + "CidrIp"),
                    permission.get(prefix + "GroupId"),
                    permission.get(prefix + "PrefixListId"),
                ]
            )
            port = permission.get("PortRange", "-1/-1")
            start, _, end = port.partition("/")
            port = "all" if port == "-1/-1" else start if start == end else port.replace("/", "-")
            targets: list[str | None] = list(peers)
            if not targets:
                targets.append(None)
            for peer in targets:
                result["inbound" if inbound else "outbound"].append(
                    {
                        "protocol": "-1"
                        if permission["IpProtocol"] == "all"
                        else permission["IpProtocol"],
                        "port_range": port,
                        "source" if inbound else "destination": peer,
                        "description": permission.get("Description", ""),
                        "policy": permission.get("Policy"),
                        "priority": permission.get("Priority"),
                        "source_port_range": permission.get("SourcePortRange"),
                    }
                )
    return result


class AlibabaProvider:
    name: Literal["alibaba"] = "alibaba"

    def __init__(
        self,
        client_factory: Callable[[AccountConfig, str], AlibabaReader] | None = None,
        discovery_region: str = "cn-hangzhou",
    ) -> None:
        self.client_factory = client_factory or AlibabaClientFactory()
        self.discovery_region = discovery_region

    @staticmethod
    def _validate(account: AccountConfig) -> None:
        if account.provider != "alibaba":
            raise ValueError("AlibabaProvider requires an alibaba account")

    def list_regions(self, account: AccountConfig) -> list[str]:
        self._validate(account)
        if isinstance(account.regions, list):
            return list(account.regions)
        client = self.client_factory(account, self.discovery_region)
        response = client.call("describe_regions")
        return sorted(region["RegionId"] for region in response["Regions"]["Region"])

    def scan(self, account: AccountConfig, region: str) -> list[NormalizedInstance]:
        self._validate(account)
        client = self.client_factory(account, region)
        group_cache: dict[str, Payload] = {}
        network_cache: dict[tuple[str, str], Payload | None] = {}
        results: list[NormalizedInstance] = []
        for page in pages(client, "describe_instances", region_id=region, max_results=100):
            for item in page.get("Instances", {}).get("Instance", []):
                enis = item.get("NetworkInterfaces", {}).get("NetworkInterface", [])
                if not enis or any(
                    not eni.get("PrivateIpSets", {}).get("PrivateIpSet") for eni in enis
                ):
                    enriched = [
                        eni
                        for eni_page in pages(
                            client,
                            "describe_network_interfaces",
                            region_id=region,
                            instance_id=item["InstanceId"],
                            max_results=100,
                        )
                        for eni in eni_page.get("NetworkInterfaceSets", {}).get(
                            "NetworkInterfaceSet", []
                        )
                    ]
                    # Preserve embedded interfaces absent from a concurrent ENI lookup.
                    by_id = {eni["NetworkInterfaceId"]: eni for eni in enis}
                    for eni in enriched:
                        eni_id = eni["NetworkInterfaceId"]
                        by_id[eni_id] = {**by_id.get(eni_id, {}), **eni}
                    enis = list(by_id.values())
                group_ids = unique(
                    [
                        *item.get("SecurityGroupIds", {}).get("SecurityGroupId", []),
                        *[
                            group_id
                            for eni in enis
                            for group_id in eni.get("SecurityGroupIds", {}).get(
                                "SecurityGroupId", []
                            )
                        ],
                    ]
                )
                for group_id in group_ids:
                    if group_id not in group_cache:
                        group_cache[group_id] = security_group(client, region, group_id)
                vpc_attrs = item.get("VpcAttributes", {})

                def network(kind: str, identifier: str | None) -> Payload | None:
                    if not identifier:
                        return None
                    key = (kind, identifier)
                    if key not in network_cache:
                        is_vpc = kind == "vpc"
                        response = client.call(
                            "describe_vpcs" if is_vpc else "describe_vswitches",
                            region_id=region,
                            **{"vpc_id" if is_vpc else "v_switch_id": identifier},
                        )
                        root, child, id_field, name_field = (
                            ("Vpcs", "Vpc", "VpcId", "VpcName")
                            if is_vpc
                            else ("VSwitches", "VSwitch", "VSwitchId", "VSwitchName")
                        )
                        row = next(
                            (
                                row
                                for row in response.get(root, {}).get(child, [])
                                if row[id_field] == identifier
                            ),
                            None,
                        )
                        network_cache[key] = (
                            {
                                "id": identifier,
                                "name": row.get(name_field),
                                "cidr": row.get("CidrBlock"),
                            }
                            if row
                            else None
                        )
                    return network_cache[key]

                results.append(
                    self._normalize(
                        account,
                        region,
                        item,
                        enis,
                        [group_cache[group_id] for group_id in group_ids],
                        network("vpc", vpc_attrs.get("VpcId")),
                        network("subnet", vpc_attrs.get("VSwitchId")),
                    )
                )
        return results

    @staticmethod
    def _normalize(
        account: AccountConfig,
        region: str,
        item: Payload,
        enis: list[Payload],
        groups: list[Payload],
        vpc: Payload | None,
        subnet: Payload | None,
    ) -> NormalizedInstance:
        attrs = item.get("VpcAttributes", {})
        private_ips = unique(
            [
                *attrs.get("PrivateIpAddress", {}).get("IpAddress", []),
                *item.get("InnerIpAddress", {}).get("IpAddress", []),
                *[ip for eni in enis for ip in eni_private_ips(eni)],
            ]
        )
        public_ips = unique(
            [
                *item.get("PublicIpAddress", {}).get("IpAddress", []),
                item.get("EipAddress", {}).get("IpAddress"),
                *[ip for eni in enis for ip in eni_public_ips(eni)],
            ]
        )
        state = item["Status"]
        return NormalizedInstance(
            provider="alibaba",
            account_id=account.account_id,
            region=region,
            instance_id=item["InstanceId"],
            name=item.get("InstanceName") or None,
            state={
                "Pending": "pending",
                "Starting": "pending",
                "Running": "running",
                "Stopping": "stopping",
                "Stopped": "stopped",
                "Released": "terminated",
            }.get(state, "unknown"),
            provider_state=state,
            instance_type=item["InstanceType"],
            private_ips=private_ips,
            public_ips=public_ips,
            tags={tag["TagKey"]: tag["TagValue"] for tag in item.get("Tags", {}).get("Tag", [])},
            launch_time=utc_datetime(item.get("CreationTime")),
            zone=item.get("ZoneId"),
            vpc_id=attrs.get("VpcId") or None,
            subnet_id=attrs.get("VSwitchId") or None,
            key_name=item.get("KeyPairName") or None,
            image_id=item.get("ImageId") or None,
            platform=item.get("OSType", "").lower() or None,
            details={
                "security_groups": groups,
                "vpc": vpc,
                "subnet": subnet,
                "network_interfaces": [
                    {
                        "id": eni["NetworkInterfaceId"],
                        "private_ips": eni_private_ips(eni),
                        "public_ip": next(iter(eni_public_ips(eni)), None),
                        "mac": eni.get("MacAddress"),
                        "security_group_ids": eni.get("SecurityGroupIds", {}).get(
                            "SecurityGroupId", []
                        ),
                    }
                    for eni in enis
                ],
                "key_pair": {"name": item["KeyPairName"]} if item.get("KeyPairName") else None,
                "iam_role": item.get("RamRoleName"),
                "image": {"id": item["ImageId"], "name": None} if item.get("ImageId") else None,
                "cpu": item.get("Cpu"),
                "memory_mib": item.get("Memory"),
                "monitoring": None,
            },
            raw=json_payload(item),
        )
