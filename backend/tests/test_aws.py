import json
from dataclasses import asdict, fields
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import Mock, patch

import boto3
import pytest
from moto import mock_aws

from cloudscope.collector.aws import AWSClientFactory, AWSProvider, BotoReader, pages, rules
from cloudscope.collector.base import NormalizedInstance, Provider
from cloudscope.config import AccountConfig
from cloudscope.db.models import Instance


@pytest.fixture
def account() -> AccountConfig:
    return AccountConfig(provider="aws", account_id="111111111111", name="test", regions="all")


@pytest.fixture
def aws() -> Any:
    with mock_aws():
        yield boto3.Session(region_name="us-east-1")


def seed(client: Any, named: bool = True) -> str:
    vpc = client.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]
    subnet = client.create_subnet(VpcId=vpc["VpcId"], CidrBlock="10.0.0.0/24")["Subnet"]
    group_id = client.create_security_group(
        VpcId=vpc["VpcId"], GroupName="test-web", Description="Test web group"
    )["GroupId"]
    client.authorize_security_group_ingress(
        GroupId=group_id,
        IpPermissions=[
            {
                "IpProtocol": "tcp",
                "FromPort": 443,
                "ToPort": 443,
                "IpRanges": [{"CidrIp": "10.0.0.0/16", "Description": "internal"}],
            }
        ],
    )
    image_id = client.register_image(Name="test-image")["ImageId"]
    item = client.run_instances(
        ImageId=image_id,
        MinCount=1,
        MaxCount=1,
        InstanceType="t3.micro",
        SubnetId=subnet["SubnetId"],
        SecurityGroupIds=[group_id],
    )["Instances"][0]
    client.create_tags(Resources=[vpc["VpcId"]], Tags=[{"Key": "Name", "Value": "test-vpc"}])
    client.create_tags(
        Resources=[subnet["SubnetId"]], Tags=[{"Key": "Name", "Value": "test-subnet"}]
    )
    if named:
        client.create_tags(Resources=[item["InstanceId"]], Tags=[{"Key": "Name", "Value": "web-1"}])
    eni = client.create_network_interface(
        SubnetId=subnet["SubnetId"],
        Groups=[group_id],
        PrivateIpAddresses=[
            {"PrivateIpAddress": "10.0.0.50", "Primary": True},
            {"PrivateIpAddress": "10.0.0.51", "Primary": False},
        ],
    )["NetworkInterface"]
    client.attach_network_interface(
        InstanceId=item["InstanceId"], NetworkInterfaceId=eni["NetworkInterfaceId"], DeviceIndex=1
    )
    return str(item["InstanceId"])


def test_scan_two_regions_full_details_and_missing_name(aws: Any, account: AccountConfig) -> None:
    first = seed(aws.client("ec2", region_name="us-east-1"))
    second = seed(aws.client("ec2", region_name="eu-central-1"), named=False)
    provider: Provider = AWSProvider(AWSClientFactory(base_session=aws))
    assert "eu-central-1" in provider.list_regions(account)
    vm = provider.scan(account, "us-east-1")[0]
    assert vm.instance_id == first
    assert vm.provider == "aws" and vm.account_id == account.account_id
    assert vm.name == "web-1" and vm.state == "running"
    assert vm.instance_type == "t3.micro" and vm.platform == "linux"
    assert {"10.0.0.50", "10.0.0.51"} <= set(vm.private_ips)
    assert len(vm.details["network_interfaces"]) == 2
    assert vm.details["vpc"]["name"] == "test-vpc"
    assert vm.details["subnet"]["name"] == "test-subnet"
    assert vm.details["image"]["name"] == "test-image"
    group = vm.details["security_groups"][0]
    assert group["name"] == "test-web"
    assert group["inbound"] == [
        {"protocol": "tcp", "port_range": "443", "source": "10.0.0.0/16", "description": "internal"}
    ]
    assert group["outbound"][0]["destination"] == "0.0.0.0/0"
    assert vm.launch_time is not None and vm.launch_time.utcoffset() == timedelta(0)
    json.dumps(asdict(vm), default=str)
    json.dumps(vm.raw)
    other = provider.scan(account, "eu-central-1")[0]
    assert other.instance_id == second and other.name is None
    assert set(vm.details) == {
        "security_groups",
        "vpc",
        "subnet",
        "network_interfaces",
        "key_pair",
        "iam_role",
        "image",
        "cpu",
        "memory_mib",
        "monitoring",
    }


def test_pagination_and_empty_region(aws: Any, account: AccountConfig) -> None:
    client = aws.client("ec2", region_name="us-east-1")
    for _ in range(6):
        client.run_instances(ImageId="ami-0123456789abcdef0", MinCount=1, MaxCount=1)
    reader = BotoReader(client)
    with patch.object(reader, "call", wraps=reader.call) as call:
        results = AWSProvider(lambda account, region: reader, page_size=5).scan(
            account, "us-east-1"
        )
    assert len(results) == 6
    assert len({vm.instance_id for vm in results}) == 6
    assert any("NextToken" in invocation.kwargs for invocation in call.call_args_list)
    assert AWSProvider(AWSClientFactory(aws)).scan(account, "eu-central-1") == []


def test_assume_role_external_id_cache_refresh_and_isolation(
    aws: Any, account: AccountConfig
) -> None:
    now = datetime.now(UTC)
    clock = Mock(return_value=now)
    sts = aws.client("sts")
    original_client = aws.client

    def client(service: str, **kwargs: Any) -> Any:
        return sts if service == "sts" else original_client(service, **kwargs)

    factory = AWSClientFactory(aws, clock=clock)
    role = account.model_copy(
        update={
            "role_arn": "arn:aws:iam::111111111111:role/cloudscope-readonly",
            "external_id": "cloudscope",
        }
    )
    with (
        patch.object(aws, "client", side_effect=client),
        patch.object(sts, "assume_role", wraps=sts.assume_role) as assume,
    ):
        factory(role, "us-east-1")
        factory(role, "eu-central-1")
        assert assume.call_count == 1
        assert assume.call_args.kwargs["ExternalId"] == "cloudscope"
        assert assume.call_args.kwargs["RoleSessionName"] == "cloudscope-collector"
        clock.return_value = now + timedelta(hours=1)
        factory(role, "us-east-1")
        assert assume.call_count == 2
        factory(role.model_copy(update={"external_id": "other"}), "us-east-1")
        assert assume.call_count == 3
        factory(account, "us-east-1")
        assert assume.call_count == 3


def test_scan_assumed_account(aws: Any, account: AccountConfig) -> None:
    role = account.model_copy(update={"role_arn": "arn:aws:iam::111111111111:role/readonly"})
    factory = AWSClientFactory(aws)
    reader = factory(role, "us-east-1")
    assert isinstance(reader, BotoReader)
    instance_id = seed(reader.client)
    assert AWSProvider(factory).scan(role, "us-east-1")[0].instance_id == instance_id


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("pending", "pending"),
        ("running", "running"),
        ("stopping", "stopping"),
        ("shutting-down", "stopping"),
        ("stopped", "stopped"),
        ("terminated", "terminated"),
        ("new-provider-state", "unknown"),
    ],
)
def test_mapping_sparse_payload_and_state(
    account: AccountConfig, state: str, expected: str
) -> None:
    item = {
        "InstanceId": "i-0123456789abcdef0",
        "State": {"Name": state},
        "InstanceType": "t3.micro",
        "CpuOptions": {"CoreCount": 2, "ThreadsPerCore": 2},
        "KeyName": "test-key",
        "IamInstanceProfile": {"Arn": "arn:aws:iam::111111111111:instance-profile/test"},
        "PublicIpAddress": "192.0.2.1",
        "NetworkInterfaces": [
            {
                "NetworkInterfaceId": "eni-test",
                "PrivateIpAddresses": [
                    {"PrivateIpAddress": "10.0.0.1", "Association": {"PublicIp": "192.0.2.2"}}
                ],
            }
        ],
    }
    result = AWSProvider._normalize(account, "us-east-1", item, {}, {}, {}, {})
    assert result.state == expected and result.provider_state == state
    assert result.public_ips == ["192.0.2.1", "192.0.2.2"]
    assert result.details["network_interfaces"][0]["public_ip"] == "192.0.2.2"
    assert result.details["cpu"] == 4 and result.details["memory_mib"] is None
    assert result.details["key_pair"] == {"name": "test-key"}
    assert result.details["iam_role"].endswith("/test")
    assert result.details["vpc"] is None and result.details["subnet"] is None


def test_rules_preserve_all_peer_types() -> None:
    permissions = [
        {
            "IpProtocol": "tcp",
            "FromPort": 80,
            "ToPort": 90,
            "Ipv6Ranges": [{"CidrIpv6": "::/0"}],
            "UserIdGroupPairs": [{"GroupId": "sg-test"}],
            "PrefixListIds": [{"PrefixListId": "pl-test"}],
        }
    ]
    assert [rule["source"] for rule in rules(permissions, "source")] == [
        "::/0",
        "sg-test",
        "pl-test",
    ]
    assert all(rule["port_range"] == "80-90" for rule in rules(permissions, "source"))


def test_configured_regions_do_not_call_cloud(account: AccountConfig) -> None:
    factory = Mock()
    assert AWSProvider(factory).list_regions(
        account.model_copy(update={"regions": ["us-east-1"]})
    ) == ["us-east-1"]
    factory.assert_not_called()


def test_normalized_fields_match_writable_model_columns() -> None:
    assert {field.name for field in fields(NormalizedInstance)} == set(
        Instance.__table__.columns.keys()
    ) - {
        "id",
        "first_seen",
        "last_observed",
        "present",
        "search_text",
    }


def test_repeated_token_fails_instead_of_silently_truncating() -> None:
    client = Mock()
    client.call.return_value = {"NextToken": "repeated"}
    with pytest.raises(RuntimeError, match="repeated"):
        list(pages(client, "describe_instances"))
