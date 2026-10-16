"""Unsaved checks and exclusions never persist supplied credentials."""

import asyncio
import logging
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_auth import CSRF, login
from test_auth import client as client
from test_auth import user as user
from test_users_api import admin as admin

from cloudscope.collector.access import AccountAccess
from cloudscope.config import AccountConfig
from cloudscope.db.models import Account, User

BODY = {"provider": "aws", "account_id": "111111111111", "name": "Test", "regions": "all"}


@pytest.mark.parametrize(
    "excluded",
    [["us-east-1", "us-east-1"], ["INVALID"], ["a"], list(f"region-{i}" for i in range(65)), None],
)
def test_exclusion_validation(client: TestClient, admin: User, excluded: object) -> None:
    login(client)
    assert (
        client.post(
            "/api/accounts", headers=CSRF, json={**BODY, "excluded_regions": excluded}
        ).status_code
        == 422
    )


def test_exclusions_round_trip_and_patch(client: TestClient, admin: User) -> None:
    login(client)
    created = client.post(
        "/api/accounts", headers=CSRF, json={**BODY, "excluded_regions": ["us-west-2"]}
    )
    assert created.status_code == 201
    assert created.json()["excluded_regions"] == ["us-west-2"]
    updated = client.patch(
        "/api/accounts/aws/111111111111",
        headers=CSRF,
        json={"excluded_regions": [], "expected_version": created.json()["configuration_version"]},
    )
    assert updated.status_code == 200 and updated.json()["excluded_regions"] == []
    assert client.get("/api/accounts").json()[0]["excluded_regions"] == []


def test_unsaved_check_auth(client: TestClient, user: User, db_session: Session) -> None:
    path = "/api/accounts/test-connection"
    assert client.post(path, headers=CSRF, json=BODY).status_code == 401
    login(client)
    assert client.post(path, headers=CSRF, json=BODY).status_code == 403
    user.is_admin = True
    db_session.commit()
    assert client.post(path, json=BODY).status_code == 403


@pytest.mark.parametrize(
    "provider,account_id", [("aws", "111111111111"), ("alibaba", "1111111111111111")]
)
def test_unsaved_keys_are_request_only(
    client: TestClient,
    admin: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    provider: str,
    account_id: str,
) -> None:
    from cloudscope.collector import access

    caplog.set_level(logging.INFO)
    stores = Mock()
    stores.create.side_effect = AssertionError("must not create a Secret")
    stores.read.side_effect = AssertionError("must not read a Secret")
    client.app.state.credential_store = stores
    client.app.state.dedicated_credentials_enabled = True
    before = db_session.scalar(select(func.count()).select_from(Account))
    calls = []

    class Factory:
        def __init__(self, *, access_test, credential_loader):
            assert access_test
            self.load = credential_loader

        def __call__(self, account, region):
            keys = self.load(account)
            calls.append(keys.access_key_id.get_secret_value())
            assert keys.secret_access_key.get_secret_value() == "fixture-secret"
            reader = Mock()
            reader.call.return_value = (
                {"Regions": [{"RegionName": "us-east-1"}, {"RegionName": "us-west-2"}]}
                if provider == "aws"
                else {"Regions": {"Region": [{"RegionId": "us-east-1"}, {"RegionId": "us-west-2"}]}}
            )
            return reader

    monkeypatch.setattr(access, "AWSClientFactory", Factory)
    monkeypatch.setattr(access, "AlibabaClientFactory", Factory)
    login(client)
    for key in ["fixture-key-one", "fixture-key-two"]:
        response = client.post(
            "/api/accounts/test-connection",
            headers=CSRF,
            json={
                **BODY,
                "provider": provider,
                "account_id": account_id,
                "connection_mode": "dedicated",
                "excluded_regions": ["us-west-2"],
                "credentials": {"access_key_id": key, "secret_access_key": "fixture-secret"},
            },
        )
        assert response.status_code == 200 and response.json() == {
            "ok": True,
            "regions": ["us-east-1"],
        }
        assert "fixture-" not in response.text
    assert calls == ["fixture-key-one", "fixture-key-two"]
    assert db_session.scalar(select(func.count()).select_from(Account)) == before
    stores.create.assert_not_called()
    stores.read.assert_not_called()
    assert "event=account_test_connection" in caplog.text and "fixture-" not in caplog.text


def test_access_excludes_and_times_out_without_leaking_errors() -> None:
    class Provider:
        def test_access(self, account):
            return ["us-east-1", "us-west-2"]

    config = AccountConfig(**BODY, excluded_regions=["us-west-2"])
    assert asyncio.run(AccountAccess({"aws": Provider()}).check(config)) == {
        "ok": True,
        "regions": 1,
        "region_ids": ["us-east-1"],
    }
    config.excluded_regions = ["us-east-1", "us-west-2"]
    assert asyncio.run(AccountAccess({"aws": Provider()}).check(config)) == {
        "ok": False,
        "error": "Region discovery failed: no regions left after exclusions",
    }

    class Broken:
        def test_access(self, account):
            raise RuntimeError("fixture-secret")

    assert asyncio.run(AccountAccess({"aws": Broken()}).check(config)) == {
        "ok": False,
        "error": "Region discovery failed: RuntimeError",
    }


def test_runtime_preview_uses_injected_access_service(client: TestClient, admin: User) -> None:
    provider = Mock()
    provider.test_access.return_value = ["us-east-1", "us-west-2"]
    client.app.state.account_access = AccountAccess({"aws": provider})
    login(client)
    result = client.post(
        "/api/accounts/test-connection",
        headers=CSRF,
        json={**BODY, "excluded_regions": ["us-west-2"]},
    )
    assert result.status_code == 200 and result.json() == {"ok": True, "regions": ["us-east-1"]}
    provider.test_access.assert_called_once()
    assert provider.test_access.call_args.args[0].account_id == BODY["account_id"]


def test_unsaved_dedicated_identity_mismatch_never_reads_inventory(
    client: TestClient, admin: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cloudscope.collector import access
    from cloudscope.collector.aws import AWSClientFactory

    sdk = Mock()
    sdk.client.return_value.get_caller_identity.return_value = {"Account": "222222222222"}
    monkeypatch.setattr(
        access,
        "AWSClientFactory",
        lambda **kwargs: AWSClientFactory(session_factory=Mock(return_value=sdk), **kwargs),
    )
    client.app.state.dedicated_credentials_enabled = True
    login(client)
    result = client.post(
        "/api/accounts/test-connection",
        headers=CSRF,
        json={
            **BODY,
            "connection_mode": "dedicated",
            "credentials": {"access_key_id": "fixture-key", "secret_access_key": "fixture-secret"},
        },
    )
    assert result.status_code == 200
    assert result.json() == {
        "ok": False,
        "error": "Region discovery failed: AccountIdentityMismatch",
    }
    assert [call.args[0] for call in sdk.client.call_args_list] == ["sts"]
    sdk.client.return_value.describe_regions.assert_not_called()


@pytest.mark.parametrize(
    "regions,discovered,excluded,expected",
    [
        ("all", [], [], "no valid regions"),
        ("all", [], ["us-east-1"], "no valid regions"),
        (["us-west-2"], ["us-east-1"], [], "no valid regions"),
        ("all", ["us-east-1"], ["us-east-1"], "no regions left after exclusions"),
    ],
)
def test_empty_region_diagnostics(regions, discovered, excluded, expected) -> None:
    provider = Mock()
    provider.test_access.return_value = discovered
    account = AccountConfig(**{**BODY, "regions": regions}, excluded_regions=excluded)
    assert asyncio.run(AccountAccess({"aws": provider}).check(account)) == {
        "ok": False,
        "error": f"Region discovery failed: {expected}",
    }
