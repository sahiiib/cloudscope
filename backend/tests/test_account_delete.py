"""Account deletion is authorized, recoverable and cannot be undone by file sync."""

from dataclasses import asdict

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session
from test_auth import CSRF, login
from test_auth import client as client
from test_auth import user as user
from test_runner import NOW, FakeProvider, instance
from test_users_api import admin as admin

from cloudscope.collector.manual import COLLECTION_LOCK_KEY
from cloudscope.collector.runner import SyncRunner
from cloudscope.config import AccountConfig
from cloudscope.db.models import Account, Instance, LoadBalancerScan, User

BODY = {"provider": "aws", "account_id": "111111111111", "name": "Demo", "regions": "all"}
URL = "/api/accounts/aws/111111111111"
DELETE = {"confirmed": True, "expected_version": 1}


def test_delete_hides_account_and_readding_restores_identity(
    admin: TestClient, db_session: Session
) -> None:
    assert admin.post("/api/accounts", json=BODY, headers=CSRF).status_code == 201
    assert (
        admin.request(
            "DELETE", URL, json={**DELETE, "expected_version": 9}, headers=CSRF
        ).status_code
        == 409
    )
    assert (
        admin.request("DELETE", URL, json={**DELETE, "confirmed": False}, headers=CSRF).status_code
        == 422
    )
    assert admin.request("DELETE", URL, json=DELETE).status_code == 403
    assert admin.request("DELETE", URL, json=DELETE, headers=CSRF).status_code == 204
    assert admin.get("/api/accounts").json() == []
    assert admin.patch(URL, json={"enabled": True}, headers=CSRF).status_code == 404
    assert admin.post(URL + "/test", headers=CSRF).status_code == 404
    db_session.expire_all()
    account = db_session.get(Account, ("aws", BODY["account_id"]))
    assert (
        account is not None and account.deleted and not account.enabled and account.source == "ui"
    )
    created = account.created_at
    assert (
        admin.post("/api/accounts", json={**BODY, "name": "Restored"}, headers=CSRF).status_code
        == 201
    )
    db_session.expire_all()
    assert not account.deleted and account.enabled and account.created_at == created
    assert account.configuration_version == 3
    assert admin.get("/api/accounts").json()[0]["name"] == "Restored"


def test_delete_file_account_creates_tombstone(admin: TestClient, db_session: Session) -> None:
    db_session.add(Account(**BODY, source="file"))
    db_session.flush()
    db_session.add(Instance(**asdict(instance()), first_seen=NOW, last_observed=NOW))
    db_session.add(
        LoadBalancerScan(
            provider="aws",
            account_id=BODY["account_id"],
            region="us-east-1",
            family="elbv2",
            status="success",
            last_attempt=NOW,
            last_success=NOW,
        )
    )
    db_session.commit()
    assert admin.get("/api/instances").json()["total"] == 1
    assert admin.request("DELETE", URL, json=DELETE, headers=CSRF).status_code == 204
    db_session.expire_all()
    row = db_session.get(Account, ("aws", BODY["account_id"]))
    assert row is not None and row.source == "ui" and row.deleted and not row.enabled
    assert admin.get("/api/instances?include_missing=true").json()["total"] == 0
    assert admin.get("/api/instances/facets").json()["accounts"] == []
    assert (
        admin.get(
            URL.replace("accounts", "instances") + "/us-east-1/i-0123456789abcdef0"
        ).status_code
        == 404
    )
    assert admin.get("/api/load-balancers/scans").json()["items"] == []
    provider = FakeProvider()
    SyncRunner(admin.app.state.auth.sessions, {"aws": provider}).run([AccountConfig(**BODY)])
    assert provider.calls == []
    assert admin.get("/api/accounts").json() == []
    assert admin.post("/api/accounts", json=BODY, headers=CSRF).status_code == 201
    assert admin.get("/api/instances").json()["total"] == 1


def test_delete_requires_admin_and_full_session(client: TestClient, user: User) -> None:
    assert client.request("DELETE", URL, json=DELETE, headers=CSRF).status_code == 401
    login(client)
    assert client.request("DELETE", URL, json=DELETE, headers=CSRF).status_code == 403


def test_delete_cannot_race_active_collection(admin: TestClient, db_session: Session) -> None:
    db_session.add(Account(**BODY, source="ui"))
    db_session.commit()
    engine = admin.app.state.auth.sessions.kw["bind"].engine
    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": COLLECTION_LOCK_KEY}
        )
        try:
            assert admin.request("DELETE", URL, json=DELETE, headers=CSRF).status_code == 409
        finally:
            connection.execute(
                text("SELECT pg_advisory_unlock(:key)"), {"key": COLLECTION_LOCK_KEY}
            )
    assert not admin.get("/api/accounts").json()[0].get("deleted", False)
