"""Alias reads share collector credentials and cannot turn a scan into a failure."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import boto3
import pytest
from alibabacloud_ram20150501 import models as ram_models
from botocore.exceptions import ClientError
from moto import mock_aws
from sqlalchemy import select
from Tea.exceptions import TeaException
from test_runner import ACCOUNT, NOW, FakeProvider
from test_runner import factory as factory

from cloudscope.collector.access import AccountAccess
from cloudscope.collector.alibaba import AlibabaClientFactory, AlibabaProvider, sdk_client
from cloudscope.collector.aws import AWSClientFactory, AWSProvider
from cloudscope.collector.runner import SyncRunner
from cloudscope.config import AccountConfig
from cloudscope.db.models import Account, SyncResult


def test_aws_alias_using_moto():
    with mock_aws():
        session = boto3.Session(region_name="us-east-1")
        provider = AWSProvider(AWSClientFactory(base_session=session))
        assert provider.get_account_alias(ACCOUNT) is None
        session.client("iam").create_account_alias(AccountAlias="demo-account")
        assert provider.get_account_alias(ACCOUNT) == "demo-account"
        session.client("iam").delete_account_alias(AccountAlias="demo-account")
        assert provider.get_account_alias(ACCOUNT) is None


@pytest.mark.parametrize("alias", ["alibaba-demo", "", None])
def test_alibaba_alias_uses_ram_sdk_global_endpoint_and_assumed_credentials(monkeypatch, alias):
    monkeypatch.setenv("ALIBABA_CLOUD_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "testing")
    configs = []
    ram = Mock()
    ram.get_account_alias_with_options.return_value = SimpleNamespace(
        body=ram_models.GetAccountAliasResponseBody(account_alias=alias)
    )
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

    def builder(service, config):
        configs.append((service, config))
        return {"ram": ram, "sts": sts}.get(service, Mock())

    account = AccountConfig(
        provider="alibaba",
        account_id="1111111111111111",
        name="Test",
        role_arn="acs:ram::1111111111111111:role/test",
        regions="all",
    )
    provider = AlibabaProvider(AlibabaClientFactory(builder, clock=lambda: NOW))
    assert provider.get_account_alias(account) == (alias or None)
    assert configs[-1][0] == "ram"
    assert configs[-1][1].endpoint == "ram.aliyuncs.com"
    assert configs[-1][1].security_token == "testing-token"
    assert configs[-1][1].access_key_id == "assumed-testing"
    assert ram.get_account_alias_with_options.call_count == 1
    # Constructing the official RAM client has no network side effects.
    from alibabacloud_ram20150501.client import Client

    assert isinstance(sdk_client("ram", configs[-1][1]), Client)


@pytest.mark.parametrize(
    "error",
    [
        ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "private-placeholder"}},
            "ListAccountAliases",
        ),
        TeaException({"code": "AccessDenied", "message": "private-placeholder"}),
    ],
)
def test_alias_refresh_once_and_failure_preserves_value_without_failing_scans(
    factory, caplog, error
):
    class AliasProvider(FakeProvider):
        alias = "demo-alias"
        calls_to_alias = 0
        failure = None

        def get_account_alias(self, account):
            self.calls_to_alias += 1
            if self.failure:
                raise self.failure
            return self.alias

    provider = AliasProvider()
    provider_name = "alibaba" if isinstance(error, TeaException) else "aws"
    account = ACCOUNT.model_copy(
        update={
            "provider": provider_name,
            "account_id": "1111111111111111" if provider_name == "alibaba" else ACCOUNT.account_id,
        }
    )
    provider.results = {
        region: [replace(vm, provider=provider_name, account_id=account.account_id) for vm in vms]
        for region, vms in provider.results.items()
    }
    runner = SyncRunner(factory, {provider_name: provider}, clock=lambda: NOW)
    assert runner.run([account]).status == "success"
    assert provider.calls_to_alias == 1  # Two region scans, one alias read.
    with factory() as session:
        row = session.get_one(Account, (provider_name, account.account_id))
        assert row.cloud_alias == "demo-alias" and row.cloud_alias_checked_at == NOW
    provider.failure = error
    runner.clock = lambda: NOW + timedelta(hours=1)
    assert runner.run([account]).status == "success"
    assert provider.calls_to_alias == 2
    with factory() as session:
        row = session.get_one(Account, (provider_name, account.account_id))
        assert row.cloud_alias == "demo-alias" and row.cloud_alias_checked_at == NOW
        assert all(result.status == "success" for result in session.scalars(select(SyncResult)))
    assert (
        f"event=account_alias_failed provider={provider_name} "
        f"account_id={account.account_id} error=AccessDenied" in caplog.text
    )
    assert "private-placeholder" not in caplog.text
    provider.failure = None
    provider.alias = None
    assert runner.run([account]).status == "success"
    with factory() as session:
        row = session.get_one(Account, (provider_name, account.account_id))
        assert row.cloud_alias is None and row.cloud_alias_checked_at == NOW + timedelta(hours=1)


@pytest.mark.parametrize("provider_name", ["aws", "alibaba"])
@pytest.mark.parametrize("phase", ["assume", "regions"])
def test_access_reports_phase_and_uses_short_sdk_timeouts(monkeypatch, provider_name, phase):
    service = AccountAccess()
    if provider_name == "aws":
        factory = service.providers["aws"].client_factory
        base, assumed = Mock(), Mock()
        factory._base, factory._session_factory = base, Mock(return_value=assumed)
        error = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "private-placeholder"}}, "Test"
        )
        base.client.return_value.assume_role.return_value = {
            "Credentials": {
                "AccessKeyId": "testing",
                "SecretAccessKey": "testing",
                "SessionToken": "testing",
                "Expiration": NOW + timedelta(hours=1),
            }
        }
        if phase == "assume":
            base.client.return_value.assume_role.side_effect = error
        else:
            assumed.client.return_value.describe_regions.side_effect = error
        account = ACCOUNT.model_copy(update={"role_arn": "arn:aws:iam::111111111111:role/test"})
    else:
        monkeypatch.setenv("ALIBABA_CLOUD_ACCESS_KEY_ID", "testing")
        monkeypatch.setenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "testing")
        factory = service.providers["alibaba"].client_factory
        sts, ecs = Mock(), Mock()
        factory.builder = lambda service, config: sts if service == "sts" else ecs
        error = TeaException({"code": "AccessDenied", "message": "private-placeholder"})
        sts.assume_role_with_options.return_value = SimpleNamespace(
            body=SimpleNamespace(
                to_map=lambda: {
                    "Credentials": {
                        "AccessKeyId": "testing",
                        "AccessKeySecret": "testing",
                        "SecurityToken": "testing",
                        "Expiration": "2026-01-01T01:00:00Z",
                    }
                }
            )
        )
        if phase == "assume":
            sts.assume_role_with_options.side_effect = error
        else:
            ecs.describe_regions_with_options.side_effect = error
        account = AccountConfig(
            provider="alibaba",
            account_id="1111111111111111",
            name="Test",
            role_arn="acs:ram::1111111111111111:role/test",
            regions="all",
        )
    result = asyncio.run(service.check(account))
    label = "Assume role failed" if phase == "assume" else "Region discovery failed"
    assert result == {"ok": False, "error": f"{label}: AccessDenied"}
    if provider_name == "aws":
        config = base.client.call_args.kwargs["config"]
        assert config.connect_timeout == 5 and config.read_timeout == 10
        assert config.retries == {"mode": "standard", "total_max_attempts": 2}
        if phase == "regions":
            assert assumed.client.call_args.kwargs["config"] is config
    else:
        options = sts.assume_role_with_options.call_args.args[-1]
        assert (options.connect_timeout, options.read_timeout, options.max_attempts) == (
            5000,
            10000,
            2,
        )
        if phase == "regions":
            options = ecs.describe_regions_with_options.call_args.args[-1]
            assert (options.connect_timeout, options.read_timeout, options.max_attempts) == (
                5000,
                10000,
                2,
            )
