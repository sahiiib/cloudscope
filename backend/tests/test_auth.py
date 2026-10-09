"""Authentication API integration tests using PostgreSQL and real Argon2 hashes."""

import base64
import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Annotated

import pytest
from argon2 import PasswordHasher
from cryptography.fernet import Fernet
from fastapi import Depends
from fastapi.testclient import TestClient
from httpx import Response
from pydantic import SecretStr
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from cloudscope.api.app import create_app
from cloudscope.auth.deps import require_admin
from cloudscope.auth.passwords import hash_password, verify_password
from cloudscope.auth.sessions import COOKIE_NAME, AuthService, LoginRateLimiter, token_hash
from cloudscope.config import Settings
from cloudscope.db.models import User, UserSession

PASSWORD = "test-password-placeholder"
NEW_PASSWORD = "new-password-placeholder"
CSRF = {"X-Requested-With": "cloudscope"}
NOW = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def user(db_session: Session) -> User:
    user = User(username="tester", password_hash=hash_password(PASSWORD))
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def client(db_session: Session, user: User) -> Iterator[TestClient]:
    settings = Settings(
        database_url=SecretStr("postgresql+psycopg://localhost/test"),
        secret_key=SecretStr(Fernet.generate_key().decode()),
        cookie_secure=True,
    )
    app = create_app(settings=settings)

    @app.get("/test/admin")
    def admin(user: Annotated[User, Depends(require_admin)]) -> dict[str, bool]:
        return {"admin": user.is_admin}

    with TestClient(app, base_url="https://testserver") as client:
        # Separate request sessions share the fixture's rollback-isolated connection.
        app.state.auth = AuthService(
            sessionmaker(
                bind=db_session.connection(),
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ),
            clock=lambda: NOW,
        )
        yield client


def login(client: TestClient, **values: str) -> Response:
    return client.post(
        "/api/auth/login", json={"username": "tester", "password": PASSWORD, **values}, headers=CSRF
    )


def test_login_me_hashed_token_and_cookie_flags(
    client: TestClient, db_session: Session, user: User
) -> None:
    response = login(client)
    assert response.status_code == 200 and response.json() == {"mfa_required": False}
    token = client.cookies[COOKIE_NAME]
    assert len(base64.urlsafe_b64decode(token + "=")) == 32
    cookie = response.headers["set-cookie"]
    for flag in ("HttpOnly", "Secure", "SameSite=lax", "Path=/", "Max-Age=43200"):
        assert flag in cookie
    stored = db_session.scalar(select(UserSession))
    assert stored is not None and stored.id_hash == token_hash(token) and stored.id_hash != token
    assert stored.mfa_passed and stored.expires_at == NOW + timedelta(hours=12)
    assert stored.ip == "testclient"
    assert client.get("/api/auth/me").json() == {
        "id": user.id,
        "username": "tester",
        "is_admin": False,
        "mfa_enabled": False,
    }
    db_session.refresh(user)
    assert user.last_login_at == NOW


def test_wrong_password_and_unknown_user_have_identical_errors(
    client: TestClient, db_session: Session, user: User
) -> None:
    wrong = login(client, password="wrong")
    unknown = login(client, username="unknown")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": "Invalid username or password"}
    assert COOKIE_NAME not in client.cookies
    db_session.refresh(user)
    assert user.failed_logins == 1
    assert db_session.scalar(select(UserSession)) is None


def test_lockout_persists_and_expires(client: TestClient, db_session: Session, user: User) -> None:
    for _ in range(5):
        assert login(client, password="wrong").status_code == 401
    db_session.refresh(user)
    assert user.failed_logins == 5 and user.locked_until == NOW + timedelta(minutes=15)
    assert login(client).status_code == 401
    client.app.state.auth.clock = lambda: NOW + timedelta(minutes=15)
    assert login(client).status_code == 200
    db_session.refresh(user)
    assert user.failed_logins == 0 and user.locked_until is None


def test_success_resets_failures(client: TestClient, db_session: Session, user: User) -> None:
    login(client, password="wrong")
    assert login(client).status_code == 200
    db_session.refresh(user)
    assert user.failed_logins == 0


def test_ip_rate_limit_applies_to_unknown_users_and_resets(client: TestClient) -> None:
    tick = [0.0]
    client.app.state.auth.limiter = LoginRateLimiter(clock=lambda: tick[0])
    for _ in range(20):
        assert login(client, username="unknown").status_code == 401
    assert login(client).status_code == 429
    tick[0] = 60
    assert login(client).status_code == 200


def test_rate_limits_are_per_ip_and_expired_entries_removed() -> None:
    tick = [0.0]
    limiter = LoginRateLimiter(lambda: tick[0])
    assert all(limiter.allow("10.0.0.1") for _ in range(20))
    assert not limiter.allow("10.0.0.1")
    assert limiter.allow("10.0.0.2")
    tick[0] = 60
    assert limiter.allow("10.0.0.3")
    assert set(limiter.attempts) == {"10.0.0.3"}


@pytest.mark.parametrize(
    "path,body",
    [
        ("login", {"username": "tester", "password": PASSWORD}),
        ("logout", {}),
        ("password", {"current_password": PASSWORD, "new_password": NEW_PASSWORD}),
    ],
)
@pytest.mark.parametrize("headers", [{}, {"X-Requested-With": "wrong"}])
def test_mutations_require_csrf(
    client: TestClient, path: str, body: dict[str, str], headers: dict[str, str]
) -> None:
    login(client)
    assert client.post(f"/api/auth/{path}", json=body, headers=headers).status_code == 403
    assert client.get("/api/auth/me").status_code == 200


def test_expired_session_rejected(client: TestClient) -> None:
    login(client)
    client.app.state.auth.clock = lambda: NOW + timedelta(hours=12)
    assert client.get("/api/auth/me").status_code == 401


def test_activity_slides_database_and_cookie_expiry(
    client: TestClient, db_session: Session
) -> None:
    login(client)
    client.app.state.auth.clock = lambda: NOW + timedelta(hours=11)
    response = client.get("/api/auth/me")
    assert response.status_code == 200 and "Max-Age=43200" in response.headers["set-cookie"]
    stored = db_session.scalar(select(UserSession))
    assert stored is not None and stored.expires_at == NOW + timedelta(hours=23)
    assert stored.created_at == NOW and stored.last_seen_at == NOW + timedelta(hours=11)


def test_login_rotates_and_logout_revokes_token(client: TestClient, db_session: Session) -> None:
    login(client)
    old = client.cookies[COOKIE_NAME]
    login(client)
    new = client.cookies[COOKIE_NAME]
    assert old != new
    assert db_session.get(UserSession, token_hash(old)) is None
    assert client.get("/api/auth/me", headers={"Cookie": f"{COOKIE_NAME}={old}"}).status_code == 401
    response = client.post("/api/auth/logout", headers=CSRF)
    assert response.status_code == 204 and response.content == b""
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert COOKIE_NAME not in client.cookies
    assert db_session.get(UserSession, token_hash(new)) is None
    assert client.get("/api/auth/me").status_code == 401


def test_half_session_restricts_access_and_allows_logout(
    client: TestClient, db_session: Session, user: User
) -> None:
    user.mfa_enabled = True
    db_session.commit()
    response = login(client)
    assert response.json() == {"mfa_required": True}
    assert "Max-Age=300" in response.headers["set-cookie"]
    stored = db_session.scalar(select(UserSession))
    assert stored is not None and not stored.mfa_passed
    assert stored.expires_at == NOW + timedelta(minutes=5)
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/test/admin").status_code == 401
    assert (
        client.post(
            "/api/auth/password",
            headers=CSRF,
            json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        ).status_code
        == 401
    )
    db_session.refresh(user)
    assert user.last_login_at is None
    assert client.post("/api/auth/logout", headers=CSRF).status_code == 204


def test_half_session_expires_without_sliding(
    client: TestClient, db_session: Session, user: User
) -> None:
    user.mfa_enabled = True
    db_session.commit()
    login(client)
    client.app.state.auth.clock = lambda: NOW + timedelta(minutes=4)
    assert client.get("/api/auth/me").status_code == 401
    client.app.state.auth.clock = lambda: NOW + timedelta(minutes=5)
    assert client.post("/api/auth/logout", headers=CSRF).status_code == 401


def test_inactive_user_cannot_login_or_use_existing_session(
    client: TestClient, db_session: Session, user: User
) -> None:
    login(client)
    user.is_active = False
    db_session.commit()
    assert client.get("/api/auth/me").status_code == 401
    assert login(client).status_code == 401


def test_admin_dependency_and_docs(client: TestClient, db_session: Session, user: User) -> None:
    assert client.get("/api/docs").status_code == 401
    login(client)
    assert client.get("/test/admin").status_code == 403
    assert client.get("/api/docs").status_code == 403
    assert client.get("/api/openapi.json").status_code == 403
    user.is_admin = True
    db_session.commit()
    assert client.get("/test/admin").status_code == 200
    assert client.get("/api/docs").status_code == 200
    assert client.get("/api/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_password_change_revokes_all_sessions(
    client: TestClient, db_session: Session, user: User
) -> None:
    login(client)
    first = client.cookies[COOKIE_NAME]
    client.cookies.clear()
    login(client)
    assert db_session.get(UserSession, token_hash(first)) is not None
    response = client.post(
        "/api/auth/password",
        headers=CSRF,
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert response.status_code == 204 and COOKIE_NAME not in client.cookies
    assert db_session.scalar(select(UserSession)) is None
    db_session.refresh(user)
    assert verify_password(NEW_PASSWORD, user.password_hash)
    assert login(client).status_code == 401
    assert login(client, password=NEW_PASSWORD).status_code == 200


def test_password_change_checks_current_password_and_length(
    client: TestClient, db_session: Session, user: User
) -> None:
    login(client)
    wrong = client.post(
        "/api/auth/password",
        headers=CSRF,
        json={"current_password": "wrong", "new_password": NEW_PASSWORD},
    )
    assert wrong.status_code == 401
    short = client.post(
        "/api/auth/password",
        headers=CSRF,
        json={"current_password": PASSWORD, "new_password": "short-secret"[:8]},
    )
    assert short.status_code == 422
    assert "short-se" not in short.text and PASSWORD not in short.text
    db_session.refresh(user)
    assert verify_password(PASSWORD, user.password_hash)
    assert client.get("/api/auth/me").status_code == 200


def test_login_persists_rehash(client: TestClient, db_session: Session, user: User) -> None:
    old = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1).hash(PASSWORD)
    user.password_hash = old
    db_session.commit()
    assert login(client).status_code == 200
    db_session.refresh(user)
    assert user.password_hash != old and not PasswordHasher().check_needs_rehash(user.password_hash)


def test_login_logs_no_passwords_or_tokens(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="cloudscope.auth.sessions")
    login(client, password="wrong-secret-placeholder")
    login(client)
    assert 'username="tester"' in caplog.text and "result=success" in caplog.text
    assert "result=invalid_credentials" in caplog.text
    assert PASSWORD not in caplog.text and "wrong-secret-placeholder" not in caplog.text
    assert client.cookies[COOKIE_NAME] not in caplog.text


def test_cookie_can_be_insecure_for_local_development(client: TestClient) -> None:
    client.app.state.auth.cookie_secure = False
    assert "Secure" not in login(client).headers["set-cookie"]


@pytest.mark.parametrize("token", ["", "unknown-token", "x" * 129])
def test_missing_and_invalid_tokens_rejected(client: TestClient, token: str) -> None:
    assert (
        client.get("/api/auth/me", headers={"Cookie": f"{COOKIE_NAME}={token}"}).status_code == 401
    )


def test_rate_limiter_is_atomic_across_threads() -> None:
    from concurrent.futures import ThreadPoolExecutor

    limiter = LoginRateLimiter(lambda: 0.0)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: limiter.allow("10.0.0.1"), range(40)))
    assert sum(results) == 20


def test_concurrent_failures_persist_without_lost_updates(migrated_engine: Engine) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from sqlalchemy import delete

    from cloudscope.db.session import create_session_factory

    factory = create_session_factory(migrated_engine)
    with factory.begin() as session:
        user = User(username="concurrent-tester", password_hash=hash_password(PASSWORD))
        session.add(user)
        session.flush()
        user_id = user.id
    settings = Settings(
        database_url=SecretStr("postgresql+psycopg://localhost/test"),
        secret_key=SecretStr(Fernet.generate_key().decode()),
    )
    try:
        with TestClient(
            create_app(migrated_engine, settings=settings, clock=lambda: NOW),
            base_url="https://testserver",
        ) as client:
            with ThreadPoolExecutor(max_workers=5) as pool:
                results = list(
                    pool.map(
                        lambda _: (
                            login(
                                client, username="concurrent-tester", password="wrong"
                            ).status_code
                        ),
                        range(5),
                    )
                )
            assert results == [401] * 5
            assert login(client, username="concurrent-tester").status_code == 401
        with factory() as session:
            user = session.get_one(User, user_id)
            assert user.failed_logins == 5 and user.locked_until == NOW + timedelta(minutes=15)
    finally:
        with factory.begin() as session:
            session.execute(delete(UserSession).where(UserSession.user_id == user_id))
            session.execute(delete(User).where(User.id == user_id))


def test_auth_unavailable_without_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLOUDSCOPE_DATABASE_URL", raising=False)
    with TestClient(create_app()) as client:
        assert client.get("/api/auth/me").status_code == 503
        assert client.get("/healthz").status_code == 200


def test_database_errors_are_sanitized(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from sqlalchemy.exc import OperationalError

    def unavailable(*args: object, **kwargs: object) -> None:
        raise OperationalError(None, None, Exception("private-error-placeholder"))

    monkeypatch.setattr(client.app.state.auth, "login", unavailable)
    response = login(client)
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
    assert "private-error" not in response.text


def test_successful_login_cleans_only_own_expired_sessions(
    client: TestClient, db_session: Session, user: User
) -> None:
    other = User(username="other-tester", password_hash=hash_password(PASSWORD))
    db_session.add(other)
    db_session.flush()
    for token, owner, expires in [
        ("expired", user.id, NOW - timedelta(seconds=1)),
        ("boundary", user.id, NOW),
        ("active", user.id, NOW + timedelta(hours=1)),
        ("other-expired", other.id, NOW - timedelta(seconds=1)),
    ]:
        db_session.add(
            UserSession(
                id_hash=token_hash(token),
                user_id=owner,
                expires_at=expires,
                ip="10.0.0.1",
                user_agent="test",
            )
        )
    db_session.commit()
    assert login(client, password="wrong").status_code == 401
    assert len(list(db_session.scalars(select(UserSession.id_hash)))) == 4
    assert login(client).status_code == 200
    remaining = set(db_session.scalars(select(UserSession.id_hash)))
    assert remaining == {
        token_hash("active"),
        token_hash("other-expired"),
        token_hash(client.cookies[COOKIE_NAME]),
    }
