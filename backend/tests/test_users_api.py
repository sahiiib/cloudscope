"""Administrator operations never expose secrets and revoke affected sessions."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_auth import CSRF, NOW, PASSWORD, login
from test_auth import client as client
from test_auth import user as user

from cloudscope.auth.passwords import verify_password
from cloudscope.db.models import User, UserSession


@pytest.fixture
def admin(client: TestClient, user: User, db_session: Session) -> TestClient:
    user.is_admin = True
    db_session.commit()
    login(client)
    return client


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("get", "/api/users", None),
        ("post", "/api/users", {"username": "new", "password": PASSWORD}),
        ("patch", "/api/users/1", {"is_active": False}),
        ("post", "/api/users/1/reset-mfa", None),
    ],
)
def test_admin_required(client: TestClient, method: str, path: str, body: dict | None) -> None:
    assert client.request(method, path, json=body, headers=CSRF).status_code == 401
    login(client)
    assert client.request(method, path, json=body, headers=CSRF).status_code == 403


def test_create_list_duplicate_and_validation(admin: TestClient, db_session: Session) -> None:
    body = {"username": "new-user", "password": PASSWORD, "is_admin": False}
    assert admin.post("/api/users", json=body).status_code == 403
    response = admin.post("/api/users", json=body, headers=CSRF)
    assert response.status_code == 201 and response.json()["is_active"]
    assert not response.json()["mfa_enabled"]
    stored = db_session.get_one(User, response.json()["id"])
    assert verify_password(PASSWORD, stored.password_hash)
    listed = admin.get("/api/users")
    assert len(listed.json()) == 2
    for secret in [PASSWORD, "password_hash", "totp_secret", "locked_until"]:
        assert secret not in listed.text and secret not in response.text
    assert admin.post("/api/users", json=body, headers=CSRF).status_code == 409
    for invalid in [{**body, "password": "too-short"}, {**body, "username": " "}]:
        response = admin.post("/api/users", json=invalid, headers=CSRF)
        assert response.status_code == 422 and "too-short" not in response.text


@pytest.mark.parametrize("operation", ["deactivate", "password", "demote", "reset-mfa"])
def test_changes_revoke_full_and_half_sessions(
    admin: TestClient, db_session: Session, operation: str
) -> None:
    response = admin.post(
        "/api/users",
        json={"username": "target", "password": PASSWORD, "is_admin": True},
        headers=CSRF,
    )
    id = response.json()["id"]
    target = db_session.get_one(User, id)
    target.mfa_enabled = True
    target.totp_secret_enc = "encrypted-placeholder"
    target.totp_last_used_step = 123
    for token, passed in [("full", True), ("half", False)]:
        db_session.add(
            UserSession(
                id_hash=token,
                user_id=id,
                mfa_passed=passed,
                expires_at=NOW,
                ip="10.0.0.1",
                user_agent="test",
            )
        )
    db_session.commit()
    if operation == "reset-mfa":
        assert admin.post(f"/api/users/{id}/reset-mfa", headers=CSRF).status_code == 204
    else:
        body = {
            "deactivate": {"is_active": False},
            "password": {"password": "new-password-placeholder"},
            "demote": {"is_admin": False},
        }[operation]
        assert admin.patch(f"/api/users/{id}", json=body, headers=CSRF).status_code == 200
    db_session.refresh(target)
    assert db_session.scalar(select(UserSession).where(UserSession.user_id == id)) is None
    assert admin.get("/api/auth/me").status_code == 200
    if operation == "reset-mfa":
        assert (
            not target.mfa_enabled
            and target.totp_secret_enc is None
            and target.totp_last_used_step is None
        )
    elif operation == "password":
        assert verify_password("new-password-placeholder", target.password_hash)
    elif operation == "deactivate":
        assert not target.is_active
        assert login(admin, username="target").status_code == 401


def test_last_admin_unknown_and_patch_validation(admin: TestClient, user: User) -> None:
    for body in [{"is_active": False}, {"is_admin": False}]:
        assert admin.patch(f"/api/users/{user.id}", json=body, headers=CSRF).status_code == 409
    assert admin.patch("/api/users/9999999", json={}, headers=CSRF).status_code == 404
    assert admin.post("/api/users/9999999/reset-mfa", headers=CSRF).status_code == 404
    for body in [{"password": "short"}, {"is_admin": None}, {"username": "renamed"}]:
        assert admin.patch(f"/api/users/{user.id}", json=body, headers=CSRF).status_code == 422
    assert admin.patch(f"/api/users/{user.id}", json={}, headers=CSRF).status_code == 200
    assert admin.post(f"/api/users/{user.id}/reset-mfa", headers=CSRF).status_code == 204
    assert admin.get("/api/auth/me").status_code == 401
