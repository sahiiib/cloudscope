import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
from alibabacloud_ecs20140526 import models as ecs_models
from alibabacloud_sts20150401 import models as sts_models
from alibabacloud_tea_openapi.models import Config
from alibabacloud_vpc20160428 import models as vpc_models

from cloudscope.collector.alibaba import (
    AlibabaClientFactory,
    AlibabaProvider,
    SDKReader,
    pages,
    sdk_client,
)
from cloudscope.collector.base import Provider
from cloudscope.config import AccountConfig


def fixture(name: str) -> dict[str, Any]:
    return json.loads((Path(__file__).parent / "fixtures/alibaba" / name).read_text())


class FakeReader:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def call(self, operation: str, **params: Any) -> dict[str, Any]:
        self.calls.append((operation, params))
        token = params.get("next_token")
        if operation == "describe_instances":
            assert params["max_results"] == 100
            return fixture("instances-2.json" if token else "instances-1.json")
        if operation == "describe_network_interfaces":
            assert params["instance_id"] == "i-test-1"
            return fixture("enis-2.json" if token else "enis-1.json")
        if operation == "describe_security_group_attribute":
            assert params["direction"] == "all"
            return fixture("sg-2.json" if token else "sg-1.json")
        if operation == "describe_vpcs":
            return fixture("vpc.json") if params["vpc_id"] == "vpc-test" else {"Vpcs": {"Vpc": []}}
        if operation == "describe_vswitches":
            return (
                fixture("vswitch.json")
                if params["v_switch_id"] == "vsw-test"
                else {"VSwitches": {"VSwitch": []}}
            )
        if operation == "describe_regions":
            return {"Regions": {"Region": [{"RegionId": "cn-hangzhou"}, {"RegionId": "me-east-1"}]}}
        raise AssertionError(f"Unexpected operation {operation}")


@pytest.fixture
def account() -> AccountConfig:
    return AccountConfig(
        provider="alibaba", account_id="1111111111111111", name="test", regions="all"
    )


def test_scan_pagination_enis_eip_rules_and_missing_network(account: AccountConfig) -> None:
    reader = FakeReader()
    provider: Provider = AlibabaProvider(lambda account, region: reader)
    assert provider.list_regions(account) == ["cn-hangzhou", "me-east-1"]
    first, second = provider.scan(account, "cn-hangzhou")
    assert first.instance_id == "i-test-1" and first.provider == "alibaba"
    assert first.account_id == account.account_id and first.region == "cn-hangzhou"
    assert first.name == "web-1" and first.state == "running"
    assert first.tags == {"env": "test"}
    assert first.private_ips == ["10.0.0.1", "10.0.0.2", "10.0.0.4"]
    assert first.public_ips == ["192.0.2.1", "192.0.2.2", "192.0.2.3"]
    assert first.launch_time == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    assert first.platform == "linux" and first.zone == "cn-hangzhou-a"
    assert first.details["cpu"] == 2 and first.details["memory_mib"] == 2048
    assert first.details["vpc"]["name"] == "test-vpc"
    assert first.details["subnet"]["cidr"] == "10.0.0.0/24"
    assert first.details["key_pair"] == {"name": "test-key"}
    assert first.details["image"] == {"id": "m-test", "name": None}
    assert first.details["network_interfaces"][0]["public_ip"] == "192.0.2.3"
    group = first.details["security_groups"][0]
    assert group["inbound"][0]["source"] == "10.0.0.0/16"
    assert group["inbound"][0]["port_range"] == "443"
    assert group["outbound"][0]["destination"] == "0.0.0.0/0"
    assert group["outbound"][0]["policy"] == "Drop"
    assert group["outbound"][0]["priority"] == "2"
    assert group["outbound"][0]["port_range"] == "all"
    assert second.name is None and second.state == "stopped"
    assert second.public_ips == ["192.0.2.1"]
    assert second.details["vpc"] is None and second.details["subnet"] is None
    assert first.raw == fixture("instances-1.json")["Instances"]["Instance"][0]
    json.dumps(first.raw)
    assert len([op for op, _ in reader.calls if op == "describe_security_group_attribute"]) == 2
    assert len([op for op, _ in reader.calls if op == "describe_network_interfaces"]) == 2
    provider.scan(account, "cn-hangzhou")
    assert len([op for op, _ in reader.calls if op == "describe_security_group_attribute"]) == 4


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("Pending", "pending"),
        ("Starting", "pending"),
        ("Running", "running"),
        ("Stopping", "stopping"),
        ("Stopped", "stopped"),
        ("Released", "terminated"),
        ("Other", "unknown"),
    ],
)
def test_sparse_classic_instance_and_state(
    account: AccountConfig, status: str, expected: str
) -> None:
    item = {
        "InstanceId": "i-sparse",
        "InstanceType": "ecs.test",
        "Status": status,
        "InnerIpAddress": {"IpAddress": ["10.0.0.1"]},
    }
    vm = AlibabaProvider._normalize(account, "cn-hangzhou", item, [], [], None, None)
    assert vm.state == expected and vm.provider_state == status
    assert vm.private_ips == ["10.0.0.1"] and vm.public_ips == []
    assert vm.launch_time is None and vm.details["key_pair"] is None
    assert vm.details["network_interfaces"] == [] and vm.raw == item


def test_official_sdk_response_shapes_match_fixtures() -> None:
    for name, model in [
        ("instances-1.json", ecs_models.DescribeInstancesResponseBody),
        ("instances-2.json", ecs_models.DescribeInstancesResponseBody),
        ("enis-1.json", ecs_models.DescribeNetworkInterfacesResponseBody),
        ("enis-2.json", ecs_models.DescribeNetworkInterfacesResponseBody),
        ("sg-1.json", ecs_models.DescribeSecurityGroupAttributeResponseBody),
        ("sg-2.json", ecs_models.DescribeSecurityGroupAttributeResponseBody),
        ("vpc.json", vpc_models.DescribeVpcsResponseBody),
        ("vswitch.json", vpc_models.DescribeVSwitchesResponseBody),
    ]:
        assert model().from_map(fixture(name)).to_map() == fixture(name)


def test_sdk_adapter_builds_real_requests_without_network() -> None:
    config = Config(
        access_key_id="testing",
        access_key_secret="testing",
        endpoint="ecs.cn-hangzhou.aliyuncs.com",
    )
    ecs, vpc = sdk_client("ecs", config), sdk_client("vpc", config)
    reader = SDKReader(ecs, vpc)
    for operation, model, params, response in [
        (
            "describe_instances",
            ecs_models.DescribeInstancesRequest,
            {"region_id": "cn-hangzhou", "max_results": 100, "next_token": "next"},
            "instances-1.json",
        ),
        ("describe_regions", ecs_models.DescribeRegionsRequest, {}, "instances-1.json"),
        (
            "describe_security_group_attribute",
            ecs_models.DescribeSecurityGroupAttributeRequest,
            {"region_id": "cn-hangzhou", "security_group_id": "sg-test", "direction": "all"},
            "sg-1.json",
        ),
        (
            "describe_network_interfaces",
            ecs_models.DescribeNetworkInterfacesRequest,
            {"region_id": "cn-hangzhou", "instance_id": "i-test-1", "max_results": 100},
            "enis-1.json",
        ),
        ("describe_vpcs", vpc_models.DescribeVpcsRequest, {"vpc_id": "vpc-test"}, "vpc.json"),
        (
            "describe_vswitches",
            vpc_models.DescribeVSwitchesRequest,
            {"v_switch_id": "vsw-test"},
            "vswitch.json",
        ),
    ]:
        call = Mock(
            return_value=SimpleNamespace(body=SimpleNamespace(to_map=lambda: fixture(response)))
        )
        client = vpc if operation in {"describe_vpcs", "describe_vswitches"} else ecs
        setattr(client, operation + "_with_options", call)
        assert reader.call(operation, **params) == fixture(response)
        request, options = call.call_args.args
        assert isinstance(request, model)
        for name, value in params.items():
            assert getattr(request, name) == value
        assert options.autoretry is True and options.max_attempts == 5
    with pytest.raises(ValueError, match="Unsupported"):
        reader.call("delete_instance")


def test_factory_direct_and_assumed_credentials(
    account: AccountConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALIBABA_CLOUD_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "testing")
    now = datetime(2026, 1, 1, tzinfo=UTC)
    clock = Mock(return_value=now)
    sts = Mock()
    sts.assume_role_with_options.return_value = SimpleNamespace(
        body=SimpleNamespace(
            to_map=lambda: {
                "Credentials": {
                    "AccessKeyId": "assumed-testing",
                    "AccessKeySecret": "assumed-testing",
                    "SecurityToken": "testing-token",
                    "Expiration": "2026-01-01T01:00:00Z",
                }
            }
        )
    )
    configs: list[tuple[str, Any]] = []

    def builder(service: str, config: Any) -> Any:
        configs.append((service, config))
        return sts if service == "sts" else Mock()

    factory = AlibabaClientFactory(builder, clock)
    factory(account, "cn-hangzhou")
    assert sts.assume_role_with_options.call_count == 0
    assert configs[0][1].endpoint == "ecs.cn-hangzhou.aliyuncs.com"
    assert configs[1][1].endpoint == "vpc.cn-hangzhou.aliyuncs.com"
    assert configs[0][1].security_token is None
    role = account.model_copy(
        update={"role_arn": "acs:ram::1111111111111111:role/readonly", "external_id": "test"}
    )
    factory(role, "cn-hangzhou")
    factory(role, "me-east-1")
    assert sts.assume_role_with_options.call_count == 1
    request = sts.assume_role_with_options.call_args.args[0]
    assert isinstance(request, sts_models.AssumeRoleRequest)
    assert request.role_arn == role.role_arn and request.duration_seconds == 3600
    assert request.role_session_name == "cloudscope-collector" and request.external_id == "test"
    assert configs[-1][1].security_token == "testing-token"
    clock.return_value = now + timedelta(minutes=56)
    factory(role, "cn-hangzhou")
    assert sts.assume_role_with_options.call_count == 2
    factory(role.model_copy(update={"account_id": "2222222222222222"}), "cn-hangzhou")
    assert sts.assume_role_with_options.call_count == 3


def test_missing_credentials_fail_without_network(
    account: AccountConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ALIBABA_CLOUD_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", raising=False)
    builder = Mock()
    with pytest.raises(ValueError, match="environment variables"):
        AlibabaClientFactory(builder)(account, "cn-hangzhou")
    builder.assert_not_called()


def test_configured_regions_skip_api_and_empty_scan(account: AccountConfig) -> None:
    factory = Mock()
    provider = AlibabaProvider(factory)
    assert provider.list_regions(account.model_copy(update={"regions": ["me-east-1"]})) == [
        "me-east-1"
    ]
    factory.assert_not_called()
    factory.return_value.call.return_value = {"Instances": {"Instance": []}}
    assert provider.scan(account, "me-east-1") == []
    assert factory.return_value.call.call_count == 1


def test_repeated_token_and_api_failure_propagate(account: AccountConfig) -> None:
    client = Mock()
    client.call.return_value = {"NextToken": "repeat"}
    with pytest.raises(RuntimeError, match="repeated"):
        list(pages(client, "describe_instances"))
    client.call.side_effect = RuntimeError("test-api-failure")
    with pytest.raises(RuntimeError, match="test-api-failure"):
        AlibabaProvider(lambda account, region: client).scan(account, "cn-hangzhou")
