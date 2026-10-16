"""Database region summaries and previews bound to an existing account identity."""

import logging
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_auth import CSRF, login
from test_auth import client as client
from test_auth import user as user
from test_users_api import admin as admin

from cloudscope.collector.access import AccountAccess
from cloudscope.config import AccountConfig
from cloudscope.credentials import CredentialError, Credentials, account_credentials
from cloudscope.db.models import Account, Instance, LoadBalancer, SyncResult, SyncRun, User

ID = "111111111111"
PATH = f"/api/accounts/aws/{ID}"
BODY = {"name": "Preview", "regions": "all"}
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def saved(session: Session, *, dedicated: bool = True, deleted: bool = False) -> Account:
    row = Account(
        provider="aws",
        account_id=ID,
        name="Saved",
        source="ui",
        regions="all",
        connection_mode="dedicated" if dedicated else "runtime",
        credential_reference="cs-" + "a" * 32 if dedicated else None,
        enabled=not deleted,
        deleted=deleted,
    )
    session.add(row)
    session.commit()
    return row


@pytest.mark.parametrize("method,suffix", [("get", "/regions"), ("post", "/test-connection")])
def test_region_controls_require_full_admin(
    client: TestClient, user: User, db_session: Session, method: str, suffix: str
) -> None:
    saved(db_session)
    kwargs = {"headers": CSRF, "json": BODY} if method == "post" else {}
    assert client.request(method, PATH + suffix, **kwargs).status_code == 401
    login(client)
    assert client.request(method, PATH + suffix, **kwargs).status_code == 403
    user.is_admin = True
    db_session.commit()
    if method == "post":
        assert client.post(PATH + suffix, json=BODY).status_code == 403
    user.mfa_enabled = True
    db_session.commit()
    login(client)
    assert client.request(method, PATH + suffix, **kwargs).status_code == 401


def test_saved_keys_bound_to_path_never_returned_or_logged(
    client: TestClient,
    admin: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from cloudscope import credentials

    row = saved(db_session)
    caplog.set_level(logging.INFO)
    store = Mock()
    store.read.return_value = Credentials(
        access_key_id="fixture-saved-key", secret_access_key="fixture-saved-secret"
    )
    monkeypatch.setattr(credentials, "credential_store", lambda: store)
    client.app.state.dedicated_credentials_enabled = True

    class Provider:
        def test_access(self, account: AccountConfig) -> list[str]:
            assert (
                account_credentials(account).access_key_id.get_secret_value() == "fixture-saved-key"
            )
            assert account.name == "Preview"
            return ["us-east-1"]

    client.app.state.account_access = AccountAccess({"aws": Provider()})
    login(client)
    # Missing body identity and mode take the immutable path identity and saved mode.
    result = client.post(PATH + "/test-connection", json=BODY, headers=CSRF)
    assert result.status_code == 200 and result.json() == {"ok": True, "regions": ["us-east-1"]}
    store.read.assert_called_once_with("cs-" + "a" * 32, "aws", ID)
    store.create.assert_not_called()
    for mismatch in (
        {"provider": "alibaba"},
        {"account_id": "222222222222"},
        {"credential_reference": "cs-" + "b" * 32},
    ):
        assert (
            client.post(
                PATH + "/test-connection", json={**BODY, **mismatch}, headers=CSRF
            ).status_code
            == 422
        )
    assert store.read.call_count == 1
    assert "fixture-" not in result.text + caplog.text
    assert "cs-" not in result.text + caplog.text
    assert "event=account_test_connection" in caplog.text
    db_session.refresh(row)
    assert row.name == "Saved" and row.configuration_version == 1


def test_new_preview_keys_override_saved_keys_without_writing(
    client: TestClient, admin: User, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cloudscope.collector import access

    row = saved(db_session)
    client.app.state.dedicated_credentials_enabled = True
    service = Mock()
    service.check.side_effect = AssertionError("must not use saved keys")
    client.app.state.account_access = service
    loaded = []

    class Factory:
        def __init__(self, *, access_test, credential_loader):
            self.load = credential_loader

        def __call__(self, account, region):
            loaded.append(self.load(account).access_key_id.get_secret_value())
            reader = Mock()
            reader.call.return_value = {"Regions": [{"RegionName": "us-east-1"}]}
            return reader

    monkeypatch.setattr(access, "AWSClientFactory", Factory)
    login(client)
    result = client.post(
        PATH + "/test-connection",
        headers=CSRF,
        json={
            **BODY,
            "credentials": {
                "access_key_id": "fixture-new-key",
                "secret_access_key": "fixture-new-secret",
            },
        },
    )
    assert result.status_code == 200 and result.json()["ok"]
    assert loaded == ["fixture-new-key"]
    service.check.assert_not_called()
    db_session.refresh(row)
    assert row.credential_reference == "cs-" + "a" * 32 and row.configuration_version == 1


@pytest.mark.parametrize("deleted", [False, True])
def test_missing_or_deleted_preview_and_regions(
    client: TestClient, admin: User, db_session: Session, deleted: bool
) -> None:
    if deleted:
        saved(db_session, deleted=True)
    login(client)
    assert client.get(PATH + "/regions").status_code == 404
    assert client.post(PATH + "/test-connection", json=BODY, headers=CSRF).status_code == 404


def test_switching_runtime_to_dedicated_needs_keys_and_flag(
    client: TestClient, admin: User, db_session: Session
) -> None:
    saved(db_session, dedicated=False)
    login(client)
    body = {**BODY, "connection_mode": "dedicated"}
    assert client.post(PATH + "/test-connection", json=body, headers=CSRF).status_code == 409
    client.app.state.dedicated_credentials_enabled = True
    assert client.post(PATH + "/test-connection", json=body, headers=CSRF).status_code == 422


def test_saved_preview_sanitizes_secret_read_failure(
    client: TestClient, admin: User, db_session: Session
) -> None:
    saved(db_session)
    provider = Mock()
    provider.test_access.side_effect = CredentialError("Secret unavailable fixture-secret")
    client.app.state.account_access = AccountAccess({"aws": provider})
    client.app.state.dedicated_credentials_enabled = True
    login(client)
    result = client.post(PATH + "/test-connection", json=BODY, headers=CSRF)
    assert result.status_code == 200 and result.json() == {
        "ok": False,
        "error": "Region discovery failed: CredentialError",
    }


def test_regions_union_counts_and_latest_scoped_history(
    client: TestClient, admin: User, db_session: Session
) -> None:
    row = saved(db_session, dedicated=False)
    row.excluded_regions = ["eu-west-1"]
    db_session.add(Account(provider="aws", account_id="222222222222", name="Other"))
    old, recent, unrelated, discovery = [
        SyncRun(trigger="manual", status="success", started_at=NOW + timedelta(days=i))
        for i in range(4)
    ]
    db_session.add_all([old, recent, unrelated, discovery])
    db_session.flush()
    for run, account_id, region in [
        (old, ID, "old-region"),
        (recent, ID, "us-east-1"),
        (recent, ID, "us-west-2"),
        (unrelated, "222222222222", "other-region"),
        (discovery, ID, "*"),
    ]:
        db_session.add(
            SyncResult(
                run_id=run.id,
                provider="aws",
                account_id=account_id,
                region=region,
                status="error" if region == "*" else "success",
                instances_seen=0,
                duration_ms=1,
            )
        )
    for i, (account_id, region, present) in enumerate(
        [
            (ID, "us-east-1", True),
            (ID, "us-east-1", True),
            (ID, "ap-south-1", True),
            (ID, "eu-west-1", False),
            ("222222222222", "us-east-1", True),
        ]
    ):
        db_session.add(
            Instance(
                provider="aws",
                account_id=account_id,
                region=region,
                instance_id=f"i-test-{i}",
                state="running",
                provider_state="running",
                instance_type="test",
                private_ips=[],
                public_ips=[],
                tags={},
                details={},
                raw={},
                present=present,
            )
        )
    for i, region in enumerate(["us-east-1", "us-east-1", "lb-only"]):
        db_session.add(
            LoadBalancer(
                provider="aws",
                account_id=ID,
                region=region,
                family="elbv2",
                load_balancer_id=f"lb-{i}",
                name="test",
                kind="application",
                state="active",
                scheme="internal",
                addresses=[],
                zones=[],
                tags={},
                raw={},
                first_seen=NOW,
                last_observed=NOW,
            )
        )
    db_session.commit()
    login(client)
    assert client.get(PATH + "/regions").json() == {
        "regions": [
            {"region": "ap-south-1", "instances": 1, "load_balancers": 0, "excluded": False},
            {"region": "eu-west-1", "instances": 0, "load_balancers": 0, "excluded": True},
            {"region": "lb-only", "instances": 0, "load_balancers": 1, "excluded": False},
            {"region": "us-east-1", "instances": 2, "load_balancers": 2, "excluded": False},
            {"region": "us-west-2", "instances": 0, "load_balancers": 0, "excluded": False},
        ]
    }


def test_never_synced_account_has_no_known_regions(
    client: TestClient, admin: User, db_session: Session
) -> None:
    saved(db_session, dedicated=False)
    login(client)
    assert client.get(PATH + "/regions").json() == {"regions": []}
