from datetime import timedelta
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree

import pyotp
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session
from test_auth import CSRF, NOW, PASSWORD, login
from test_auth import client as client
from test_auth import user as user

from cloudscope.auth.sessions import COOKIE_NAME, token_hash
from cloudscope.auth.totp import MFAService
from cloudscope.db.models import User, UserSession


@pytest.fixture
def mfa_client(client: TestClient) -> TestClient:
    client.app.state.mfa = MFAService(client.app.state.auth, Fernet(Fernet.generate_key()))
    assert login(client).status_code == 200
    return client


def setup(client: TestClient) -> pyotp.TOTP:
    response = client.post("/api/auth/mfa/setup", headers=CSRF)
    assert response.status_code == 200
    return pyotp.TOTP(parse_qs(urlparse(response.json()["otpauth_uri"]).query)["secret"][0])


def enable(client: TestClient) -> pyotp.TOTP:
    totp = setup(client)
    assert (
        client.post("/api/auth/mfa/enable", headers=CSRF, json={"code": totp.at(NOW)}).status_code
        == 204
    )
    return totp


def test_setup_qr_uri_encryption_and_pending_state(
    mfa_client: TestClient, db_session: Session, user: User
) -> None:
    response = mfa_client.post("/api/auth/mfa/setup", headers=CSRF)
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    data = response.json()
    parsed = urlparse(data["otpauth_uri"])
    assert parsed.scheme == "otpauth" and parsed.netloc == "totp"
    params = parse_qs(parsed.query)
    assert params["issuer"] == ["cloudscope"]
    assert "tester" in parsed.path
    assert ElementTree.fromstring(data["qr_svg"]).tag == "{http://www.w3.org/2000/svg}svg"
    db_session.refresh(user)
    assert not user.mfa_enabled and user.totp_secret_enc is not None
    assert params["secret"][0] not in user.totp_secret_enc
    assert (
        mfa_client.app.state.mfa.cipher.decrypt(user.totp_secret_enc.encode()).decode()
        == params["secret"][0]
    )


def test_enable_replay_rejection_and_rotated_login(
    mfa_client: TestClient, db_session: Session, user: User
) -> None:
    totp = enable(mfa_client)
    assert mfa_client.get("/api/auth/me").json()["mfa_enabled"]
    assert login(mfa_client).json() == {"mfa_required": True}
    old = mfa_client.cookies[COOKIE_NAME]
    assert mfa_client.get("/api/auth/me").status_code == 401
    assert (
        mfa_client.post(
            "/api/auth/mfa/verify-login", headers=CSRF, json={"code": totp.at(NOW)}
        ).status_code
        == 401
    )
    later = NOW + timedelta(seconds=30)
    mfa_client.app.state.auth.clock = lambda: later
    response = mfa_client.post(
        "/api/auth/mfa/verify-login", headers=CSRF, json={"code": totp.at(later)}
    )
    assert response.status_code == 200
    new = mfa_client.cookies[COOKIE_NAME]
    assert new != old and "HttpOnly" in response.headers["set-cookie"]
    assert (
        "Secure" in response.headers["set-cookie"]
        and "Max-Age=43200" in response.headers["set-cookie"]
    )
    assert db_session.get(UserSession, token_hash(old)) is None
    stored = db_session.get(UserSession, token_hash(new))
    assert stored is not None and stored.mfa_passed
    assert stored.created_at == later and stored.expires_at == later + timedelta(hours=12)
    db_session.refresh(user)
    assert user.last_login_at == later
    assert mfa_client.get("/api/auth/me").status_code == 200


@pytest.mark.parametrize("code", ["invalid", "12345", "１２３４５６", "1234567"])
def test_five_failed_codes_delete_half_session(
    mfa_client: TestClient, db_session: Session, code: str
) -> None:
    enable(mfa_client)
    login(mfa_client)
    hashed = token_hash(mfa_client.cookies[COOKIE_NAME])
    for attempt in range(1, 6):
        assert (
            mfa_client.post(
                "/api/auth/mfa/verify-login", headers=CSRF, json={"code": code}
            ).status_code
            == 401
        )
        db_session.expire_all()
        stored = db_session.get(UserSession, hashed)
        if attempt < 5:
            assert stored is not None and stored.mfa_failures == attempt
        else:
            assert stored is None


@pytest.mark.parametrize("offset,expected", [(-2, 401), (-1, 200), (0, 200), (1, 200), (2, 401)])
def test_window_and_out_of_window_codes(mfa_client: TestClient, offset: int, expected: int) -> None:
    totp = enable(mfa_client)
    login(mfa_client)
    later = NOW + timedelta(minutes=2)
    mfa_client.app.state.auth.clock = lambda: later
    response = mfa_client.post(
        "/api/auth/mfa/verify-login",
        headers=CSRF,
        json={"code": totp.at(later + timedelta(seconds=offset * 30))},
    )
    assert response.status_code == expected


def test_half_session_expiry_and_protected_mfa_routes(mfa_client: TestClient) -> None:
    totp = enable(mfa_client)
    login(mfa_client)
    for route, body in [
        ("setup", {}),
        ("enable", {"code": totp.at(NOW)}),
        ("disable", {"password": PASSWORD, "code": totp.at(NOW)}),
    ]:
        assert mfa_client.post(f"/api/auth/mfa/{route}", headers=CSRF, json=body).status_code == 401
    later = NOW + timedelta(minutes=5)
    mfa_client.app.state.auth.clock = lambda: later
    assert (
        mfa_client.post(
            "/api/auth/mfa/verify-login", headers=CSRF, json={"code": totp.at(later)}
        ).status_code
        == 401
    )


@pytest.mark.parametrize(
    "route,body",
    [
        ("setup", {}),
        ("enable", {"code": "123456"}),
        ("disable", {"password": PASSWORD, "code": "123456"}),
        ("verify-login", {"code": "123456"}),
    ],
)
def test_mfa_csrf_required(mfa_client: TestClient, route: str, body: dict[str, str]) -> None:
    assert mfa_client.post(f"/api/auth/mfa/{route}", json=body).status_code == 403


def test_disable_requires_password_and_fresh_code(
    mfa_client: TestClient, db_session: Session, user: User
) -> None:
    totp = enable(mfa_client)
    assert (
        mfa_client.post(
            "/api/auth/mfa/disable", headers=CSRF, json={"password": PASSWORD, "code": totp.at(NOW)}
        ).status_code
        == 401
    )
    later = NOW + timedelta(seconds=30)
    mfa_client.app.state.auth.clock = lambda: later
    assert (
        mfa_client.post(
            "/api/auth/mfa/disable",
            headers=CSRF,
            json={"password": "wrong", "code": totp.at(later)},
        ).status_code
        == 401
    )
    assert (
        mfa_client.post(
            "/api/auth/mfa/disable",
            headers=CSRF,
            json={"password": PASSWORD, "code": totp.at(later)},
        ).status_code
        == 204
    )
    db_session.refresh(user)
    assert (
        not user.mfa_enabled and user.totp_secret_enc is None and user.totp_last_used_step is None
    )
    assert login(mfa_client).json() == {"mfa_required": False}


def test_enrollment_states_and_no_secret_overwrite(
    mfa_client: TestClient, db_session: Session, user: User
) -> None:
    assert (
        mfa_client.post("/api/auth/mfa/enable", headers=CSRF, json={"code": "123456"}).status_code
        == 409
    )
    enable(mfa_client)
    db_session.refresh(user)
    encrypted = user.totp_secret_enc
    assert mfa_client.post("/api/auth/mfa/setup", headers=CSRF).status_code == 409
    assert (
        mfa_client.post("/api/auth/mfa/enable", headers=CSRF, json={"code": "123456"}).status_code
        == 409
    )
    db_session.refresh(user)
    assert user.totp_secret_enc == encrypted


def test_enabling_revokes_other_sessions(mfa_client: TestClient, db_session: Session) -> None:
    old = mfa_client.cookies[COOKIE_NAME]
    mfa_client.cookies.clear()
    login(mfa_client)
    enable(mfa_client)
    assert db_session.get(UserSession, token_hash(old)) is None
    assert mfa_client.get("/api/auth/me").status_code == 200


def test_bad_encryption_key_fails_closed(mfa_client: TestClient) -> None:
    totp = enable(mfa_client)
    login(mfa_client)
    mfa_client.app.state.mfa.cipher = Fernet(Fernet.generate_key())
    response = mfa_client.post(
        "/api/auth/mfa/verify-login", headers=CSRF, json={"code": totp.at(NOW)}
    )
    assert response.status_code == 503 and response.json() == {"detail": "MFA unavailable"}
    assert mfa_client.get("/api/auth/me").status_code == 401


def test_wrong_numeric_code_is_rejected(mfa_client: TestClient) -> None:
    totp = enable(mfa_client)
    login(mfa_client)
    valid = {totp.at(NOW + timedelta(seconds=offset * 30)) for offset in (-1, 0, 1)}
    wrong = next(f"{number:06d}" for number in range(4) if f"{number:06d}" not in valid)
    assert (
        mfa_client.post(
            "/api/auth/mfa/verify-login", headers=CSRF, json={"code": wrong}
        ).status_code
        == 401
    )


def test_mfa_audit_does_not_log_secret_or_code(
    mfa_client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    caplog.set_level(logging.INFO, logger="cloudscope.auth.sessions")
    totp = enable(mfa_client)
    login(mfa_client)
    later = NOW + timedelta(seconds=30)
    mfa_client.app.state.auth.clock = lambda: later
    code = totp.at(later)
    assert (
        mfa_client.post("/api/auth/mfa/verify-login", headers=CSRF, json={"code": code}).status_code
        == 200
    )
    messages = "\n".join(
        record.getMessage()
        for record in caplog.records
        if record.name == "cloudscope.auth.sessions"
    )
    assert "mfa_success" in messages
    assert totp.secret not in messages and code not in messages


def test_same_code_cannot_authenticate_two_concurrent_sessions(migrated_engine: Engine) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from fastapi import HTTPException
    from sqlalchemy import delete, select

    from cloudscope.auth.passwords import hash_password
    from cloudscope.auth.sessions import AuthService
    from cloudscope.db.session import create_session_factory

    factory = create_session_factory(migrated_engine)
    cipher = Fernet(Fernet.generate_key())
    secret = pyotp.random_base32()
    with factory.begin() as session:
        account = User(
            username="mfa-concurrent",
            password_hash=hash_password(PASSWORD),
            mfa_enabled=True,
            totp_secret_enc=cipher.encrypt(secret.encode()).decode(),
        )
        session.add(account)
        session.flush()
        user_id = account.id
        for token in ("first-half", "second-half"):
            session.add(
                UserSession(
                    id_hash=token_hash(token),
                    user_id=user_id,
                    created_at=NOW,
                    expires_at=NOW + timedelta(minutes=5),
                    ip="10.0.0.1",
                    user_agent="test",
                )
            )
    try:
        service = MFAService(AuthService(factory, clock=lambda: NOW), cipher)
        barrier = Barrier(2)

        def verify(token: str) -> int:
            barrier.wait(timeout=5)
            try:
                service.verify_login(token, pyotp.TOTP(secret).at(NOW))
                return 200
            except HTTPException as exc:
                return exc.status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(verify, ["first-half", "second-half"])) == [200, 401]
        with factory() as session:
            sessions = list(
                session.scalars(select(UserSession).where(UserSession.user_id == user_id))
            )
            assert sum(stored.mfa_passed for stored in sessions) == 1
            assert sum(stored.mfa_failures for stored in sessions) == 1
    finally:
        with factory.begin() as session:
            session.execute(delete(User).where(User.id == user_id))
