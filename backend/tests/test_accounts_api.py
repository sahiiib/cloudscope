"""Account mutations enforce permissions and validate without reflecting inputs."""

import logging
from threading import Event

import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_auth import CSRF, login
from test_auth import client as client
from test_auth import user as user
from test_users_api import admin as admin

from cloudscope.collector.access import AccountAccess
from cloudscope.config import AccountConfig
from cloudscope.db.models import Account, Instance, SyncRun, User

BODY = {"provider": "aws", "account_id": "111111111111", "name": "Test", "regions": "all"}
URL = "/api/accounts/aws/111111111111"


@pytest.mark.parametrize(
    "method,path", [("post", "/api/accounts"), ("patch", URL), ("post", URL + "/test")]
)
def test_auth_and_csrf(
    client: TestClient, user: User, db_session: Session, method: str, path: str
) -> None:
    assert client.request(method, path, json=BODY, headers=CSRF).status_code == 401
    login(client)
    assert client.request(method, path, json=BODY, headers=CSRF).status_code == 403
    user.is_admin = True
    db_session.commit()
    assert client.request(method, path, json=BODY).status_code == 403
    user.mfa_enabled = True
    db_session.commit()
    login(client)
    assert client.request(method, path, json=BODY, headers=CSRF).status_code == 401


@pytest.mark.parametrize(
    "field,value",
    [
        ("provider", "unknown-provider"),
        ("account_id", "123"),
        ("account_id", "１２３４５６７８９０１２"),
        ("account_id", "a" * 12),
        ("name", ""),
        ("name", " bad"),
        ("name", "bad "),
        ("name", "bad\nname"),
        ("name", "bad\x7fname"),
        ("name", "x" * 65),
        ("role_arn", "arn:aws:iam::222222222222:role/test"),
        ("role_arn", "acs:ram::111111111111:role/test"),
        ("role_arn", ""),
        ("external_id", "a"),
        ("external_id", "x" * 1225),
        ("external_id", "bad value"),
        ("regions", []),
        ("regions", ["us-east-1", "us-east-1"]),
        ("regions", ["UpperCase"]),
        ("regions", ["x"]),
        ("regions", ["x" * 33]),
        ("regions", ["a_b"]),
        ("regions", "us-east-1"),
        ("regions", None),
        ("enabled", "true"),
        ("enabled", None),
        ("unknown", "private-placeholder"),
    ],
)
def test_create_validation(admin: TestClient, field: str, value: object) -> None:
    response = admin.post("/api/accounts", json={**BODY, field: value}, headers=CSRF)
    assert response.status_code == 422
    assert any(field in error["loc"] for error in response.json()["detail"])
    assert "private-placeholder" not in response.text
    assert all("input" not in error and "ctx" not in error for error in response.json()["detail"])


@pytest.mark.parametrize(
    "patch",
    [
        {"provider": "alibaba"},
        {"account_id": "222222222222"},
        {"name": None},
        {"name": " bad"},
        {"enabled": None},
        {"regions": None},
        {"regions": []},
        {"role_arn": "arn:aws:iam::222222222222:role/test"},
        {"external_id": "!"},
        {"unknown": "private-placeholder"},
    ],
)
def test_patch_validation(admin: TestClient, patch: dict) -> None:
    assert admin.post("/api/accounts", json=BODY, headers=CSRF).status_code == 201
    response = admin.patch(URL, json=patch, headers=CSRF)
    assert response.status_code == 422
    assert "private-placeholder" not in response.text


def test_create_patch_clear_duplicate_and_audit(
    admin: TestClient, caplog: pytest.LogCaptureFixture, db_session: Session
) -> None:
    caplog.set_level(logging.INFO)
    body = {
        **BODY,
        "role_arn": "arn:aws:iam::111111111111:role/test",
        "external_id": "private-placeholder",
        "regions": ["eu-central-1"],
    }
    created = admin.post("/api/accounts", json=body, headers=CSRF)
    assert created.status_code == 201
    assert created.json() == {
        **body,
        "enabled": True,
        "source": "ui",
        "last_success_at": None,
        "instance_count": 0,
        "cloud_alias": None,
    }
    assert admin.post("/api/accounts", json=body, headers=CSRF).status_code == 409
    assert admin.get("/api/accounts").json() == [created.json()]
    for enabled in (False, True):
        patched = admin.patch(URL, json={"enabled": enabled}, headers=CSRF)
        assert patched.status_code == 200 and patched.json()["enabled"] is enabled
        assert patched.json()["regions"] == ["eu-central-1"]
    patched = admin.patch(URL, json={"role_arn": None, "external_id": None}, headers=CSRF)
    assert patched.json()["role_arn"] is None and patched.json()["external_id"] is None
    assert "event=account_create actor=" in caplog.text
    assert "changed=external_id,role_arn" in caplog.text
    assert "private-placeholder" not in caplog.text and body["role_arn"] not in caplog.text
    stored = db_session.get_one(Account, ("aws", BODY["account_id"]))
    assert stored.updated_at >= stored.created_at


def test_file_readonly_unknown_and_alibaba(admin: TestClient, db_session: Session) -> None:
    db_session.add(Account(**BODY, source="file"))
    db_session.commit()
    assert admin.post("/api/accounts", json=BODY, headers=CSRF).status_code == 409
    assert admin.patch(URL, json={"enabled": False}, headers=CSRF).status_code == 409
    assert admin.patch("/api/accounts/aws/222222222222", json={}, headers=CSRF).status_code == 404
    assert admin.post("/api/accounts/aws/222222222222/test", headers=CSRF).status_code == 404
    alibaba = {
        **BODY,
        "provider": "alibaba",
        "account_id": "1111111111111111",
        "role_arn": "acs:ram::1111111111111111:role/test",
    }
    for invalid in (
        {"account_id": "111111111111"},
        {"external_id": "test"},
        {"role_arn": "acs:ram::2222222222222222:role/test"},
    ):
        assert (
            admin.post("/api/accounts", json={**alibaba, **invalid}, headers=CSRF).status_code
            == 422
        )
    assert admin.post("/api/accounts", json=alibaba, headers=CSRF).status_code == 201


@pytest.mark.parametrize("outcome", ["success", "denied", "timeout"])
def test_access_no_inventory_writes(admin: TestClient, db_session: Session, outcome: str) -> None:
    assert admin.post("/api/accounts", json=BODY, headers=CSRF).status_code == 201
    release = Event()

    class Provider:
        def test_access(self, account: AccountConfig) -> list[str]:
            assert account.account_id == BODY["account_id"]
            if outcome == "denied":
                raise ClientError(
                    {"Error": {"Code": "AccessDenied", "Message": "private-placeholder"}},
                    "DescribeRegions",
                )
            if outcome == "timeout":
                release.wait(2)
            return ["us-east-1", "eu-central-1"]

    admin.app.state.account_access = AccountAccess({"aws": Provider()}, timeout=0.02)
    try:
        response = admin.post(URL + "/test", headers=CSRF)
        assert response.status_code == 200
        if outcome == "success":
            assert response.json() == {"ok": True, "regions": 2}
        else:
            expected = "AccessDenied" if outcome == "denied" else "TimeoutError"
            assert response.json() == {"ok": False, "error": f"Region discovery failed: {expected}"}
        assert "private-placeholder" not in response.text
        assert db_session.scalar(select(func.count()).select_from(Instance)) == 0
        assert db_session.scalar(select(func.count()).select_from(SyncRun)) == 0
    finally:
        release.set()
