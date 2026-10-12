"""Access checks force discovery and never invoke inventory APIs."""

from unittest.mock import Mock

import pytest

from cloudscope.collector.alibaba import AlibabaProvider
from cloudscope.collector.aws import AWSClientFactory, AWSProvider
from cloudscope.config import AccountConfig


@pytest.mark.parametrize(
    "provider_type,response",
    [
        (AWSProvider, {"Regions": [{"RegionName": "us-east-1"}]}),
        (AlibabaProvider, {"Regions": {"Region": [{"RegionId": "eu-central-1"}]}}),
    ],
)
def test_access_discovers_even_with_explicit_regions(provider_type, response):
    reader = Mock()
    reader.call.return_value = response
    factory = Mock(return_value=reader)
    provider = provider_type(client_factory=factory)
    account = AccountConfig(
        provider=provider.name,
        account_id="111111111111",
        name="test",
        regions=["eu-central-1"],
        role_arn="test-role",
        external_id="test-id",
    )
    assert len(provider.test_access(account)) == 1
    assert factory.call_count == reader.call.call_count == 1
    assert factory.call_args.args[0].role_arn == "test-role"
    assert factory.call_args.args[0].external_id == "test-id"
    assert reader.call.call_args.args == ("describe_regions",)
    assert account.regions == ["eu-central-1"]


def test_aws_access_assumes_role_before_discovery():
    from datetime import UTC, datetime, timedelta

    base, assumed = Mock(), Mock()
    base.client.return_value.assume_role.return_value = {
        "Credentials": {
            "AccessKeyId": "testing",
            "SecretAccessKey": "testing",
            "SessionToken": "testing",
            "Expiration": datetime.now(UTC) + timedelta(hours=1),
        }
    }
    assumed.client.return_value.describe_regions.return_value = {"Regions": []}
    provider = AWSProvider(
        client_factory=AWSClientFactory(
            base_session=base, session_factory=Mock(return_value=assumed)
        )
    )
    account = AccountConfig(
        provider="aws",
        account_id="111111111111",
        name="test",
        regions="all",
        role_arn="arn:aws:iam::111111111111:role/test",
        external_id="test-id",
    )
    assert provider.test_access(account) == []
    base.client.return_value.assume_role.assert_called_once_with(
        RoleArn=account.role_arn, RoleSessionName="cloudscope-collector", ExternalId="test-id"
    )
    assumed.client.return_value.describe_regions.assert_called_once_with(AllRegions=False)


def test_aws_access_with_moto():
    import boto3
    from moto import mock_aws

    with mock_aws():
        provider = AWSProvider(
            client_factory=AWSClientFactory(base_session=boto3.Session(region_name="us-east-1"))
        )
        account = AccountConfig(
            provider="aws",
            account_id="111111111111",
            name="test",
            regions=["eu-central-1"],
            role_arn="arn:aws:iam::111111111111:role/test",
            external_id="test-id",
        )
        regions = provider.test_access(account)
        assert "us-east-1" in regions and "eu-central-1" in regions
