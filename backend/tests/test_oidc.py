"""Fake OIDC issuer/JWKS/token endpoint. No real Keycloak or credentials."""

import base64
import hashlib
import json
import logging
import secrets
import time
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select
from test_auth import CSRF, PASSWORD
from test_auth import client as client
from test_auth import user as user

from cloudscope.auth.oidc import COOKIE, CallbackLogFilter, OIDCService, safe_next
from cloudscope.auth.sessions import COOKIE_NAME, token_hash
from cloudscope.auth.totp import MFAService
from cloudscope.config import Settings
from cloudscope.db.models import OIDCLoginState, User, UserSession

ISSUER = "https://idp.example.com/realms/test"
PUBLIC = "https://app.example.com"


class Issuer:
    def __init__(self):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.kid = "first"
        self.codes = {}
        self.calls = []
        self.jwks_calls = 0
        self.fail_exchange = False

    def handle(self, request):
        self.calls.append(request)
        if request.url.path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": ISSUER + "/authorize",
                    "token_endpoint": ISSUER + "/token",
                    "jwks_uri": ISSUER + "/jwks",
                    "end_session_endpoint": ISSUER + "/logout",
                },
            )
        if request.url.path.endswith("/jwks"):
            self.jwks_calls += 1
            key = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
            return httpx.Response(
                200, json={"keys": [{**key, "kid": self.kid, "use": "sig", "alg": "RS256"}]}
            )
        if request.url.path.endswith("/token"):
            if self.fail_exchange:
                return httpx.Response(400, json={"error_description": "sensitive provider body"})
            body = parse_qs(request.content.decode())
            claims, challenge = self.codes[body["code"][0]]
            verifier = body["code_verifier"][0]
            assert (
                base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
                .rstrip(b"=")
                .decode()
                == challenge
            )
            assert body["redirect_uri"] == [PUBLIC + "/api/auth/oidc/callback"]
            assert body["client_secret"] == ["fake-client-secret"]
            return httpx.Response(
                200,
                json={
                    "id_token": jwt.encode(
                        claims, self.key, algorithm="RS256", headers={"kid": self.kid}
                    ),
                    "access_token": "never-store-access-token",
                },
            )
        raise AssertionError(f"Unexpected fake endpoint {request.url.path}")


@pytest.fixture
def sso(client):
    issuer = Issuer()
    auth = client.app.state.auth
    auth.sso_enabled = True
    client.app.state.mfa = MFAService(auth, Fernet(Fernet.generate_key()))
    settings = Settings(
        database_url="postgresql+psycopg://localhost/test",
        secret_key=Fernet.generate_key().decode(),
        oidc_issuer=ISSUER,
        oidc_client_secret="fake-client-secret",
        public_url=PUBLIC,
    )
    service = OIDCService(
        auth, settings, httpx.Client(transport=httpx.MockTransport(issuer.handle))
    )
    client.app.state.oidc = service
    yield issuer
    service.client.close()


def start(client, issuer, changes=None, next_path="/nat-gateways", omit=()):
    response = client.get(
        "/api/auth/oidc/login", params={"next": next_path}, follow_redirects=False
    )
    assert response.status_code == 302
    query = {
        key: values[0]
        for key, values in parse_qs(urlsplit(response.headers["location"]).query).items()
    }
    assert query["code_challenge_method"] == "S256"
    assert query["response_type"] == "code" and query["scope"] == "openid profile"
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "sub": "subject-1",
        "aud": "cloudscope",
        "iat": now,
        "exp": now + 300,
        "nonce": query["nonce"],
        "preferred_username": "teammate",
        "resource_access": {"cloudscope": {"roles": ["cloudscope-user"]}},
        **(changes or {}),
    }
    for key in omit:
        claims.pop(key, None)
    code = secrets.token_urlsafe(20)
    issuer.codes[code] = (claims, query["code_challenge"])
    return {"state": query["state"], "code": code}


def finish(client, params):
    return client.get("/api/auth/oidc/callback", params=params, follow_redirects=False)


def test_valid_login_pkce_cookie_state_and_logout(client, db_session, sso, caplog):
    caplog.set_level(logging.INFO, logger="cloudscope.auth.oidc")
    params = start(client, sso)
    state = db_session.scalar(select(OIDCLoginState))
    assert (
        state.id_hash == token_hash(client.cookies[COOKIE])
        and state.state != client.cookies[COOKIE]
    )
    result = finish(client, params)
    assert result.status_code == 302 and result.headers["location"] == "/nat-gateways"
    cookie = result.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=lax" in cookie
    assert COOKIE not in client.cookies
    assert client.get("/api/auth/me").json()["is_sso"] is True
    stored = db_session.scalar(select(User).where(User.oidc_subject == "subject-1"))
    assert stored.password_hash is None and not stored.is_admin
    session = db_session.scalar(select(UserSession))
    assert session.mfa_passed and session.id_hash == token_hash(client.cookies[COOKIE_NAME])
    assert session.expires_at - session.created_at == timedelta(hours=12)
    assert db_session.scalar(select(OIDCLoginState)) is None
    assert finish(client, params).headers["location"] == "/login?error=sso"
    logout = client.post("/api/auth/logout", headers=CSRF)
    assert logout.status_code == 200
    parsed = urlsplit(logout.json()["logout_url"])
    assert parsed.path.endswith("/logout")
    assert parse_qs(parsed.query) == {
        "client_id": ["cloudscope"],
        "post_logout_redirect_uri": [PUBLIC + "/"],
    }
    assert COOKIE_NAME not in client.cookies
    assert (
        params["code"] not in caplog.text
        and "fake-client-secret" not in caplog.text
        and "never-store-access-token" not in caplog.text
    )
    assert "event=sso_login" in caplog.text and "subject-1" in caplog.text


@pytest.mark.parametrize(
    "changes,omit",
    [
        ({"nonce": "wrong"}, ()),
        ({"aud": "other"}, ()),
        ({"iss": ISSUER + "/other"}, ()),
        ({"exp": -120}, ()),
        ({"iat": 120}, ()),
        ({"azp": "other"}, ()),
        ({"aud": ["cloudscope", "other"]}, ()),
        ({}, ("exp",)),
        ({}, ("iat",)),
        ({}, ("sub",)),
        ({}, ("nonce",)),
    ],
)
def test_invalid_id_tokens_fail_closed(client, db_session, sso, changes, omit):
    changes = dict(changes)
    for field in ("exp", "iat"):
        if field in changes:
            changes[field] += int(time.time())
    assert (
        finish(client, start(client, sso, changes, omit=omit)).headers["location"]
        == "/login?error=sso"
    )
    assert COOKIE_NAME not in client.cookies
    assert db_session.scalar(select(UserSession)) is None


@pytest.mark.parametrize("mode", ["wrong-state", "expired", "missing-cookie", "provider-error"])
def test_state_binding_and_ttl(client, db_session, sso, mode):
    params = start(client, sso)
    if mode == "wrong-state":
        params["state"] = "wrong"
    if mode == "provider-error":
        params["error"] = "access_denied"
    if mode == "missing-cookie":
        client.cookies.clear()
    if mode == "expired":
        state = db_session.scalar(select(OIDCLoginState))
        state.created_at -= timedelta(minutes=11)
        db_session.commit()
    assert finish(client, params).headers["location"] == "/login?error=sso"
    assert not any(call.url.path.endswith("/token") for call in sso.calls)
    assert db_session.scalar(select(UserSession)) is None


def test_role_sync_clash_and_identity_not_username(client, db_session, sso):
    def roles(value):
        return {"resource_access": {"cloudscope": {"roles": value}}}

    result = finish(
        client, start(client, sso, {"preferred_username": "tester", **roles(["cloudscope-admin"])})
    )
    assert result.headers["location"] == "/nat-gateways"
    me = client.get("/api/auth/me").json()
    assert me["username"] == "tester@sso" and me["is_admin"]
    finish(
        client, start(client, sso, {"preferred_username": "renamed", **roles(["cloudscope-user"])})
    )
    assert client.get("/api/auth/me").json() == {**me, "is_admin": False}
    finish(client, start(client, sso, {"preferred_username": "tester", "sub": "subject-2"}))
    assert client.get("/api/auth/me").json()["username"] == "tester@sso2"
    client.cookies.clear()
    assert (
        finish(client, start(client, sso, roles([]))).headers["location"]
        == "/login?error=not-authorized"
    )
    assert COOKIE_NAME not in client.cookies


def test_unknown_kid_refresh_and_exchange_failure(client, sso, caplog):
    finish(client, start(client, sso))
    assert sso.jwks_calls == 1
    sso.kid = "rotated"
    sso.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert finish(client, start(client, sso)).headers["location"] == "/nat-gateways"
    assert sso.jwks_calls == 2
    sso.fail_exchange = True
    params = start(client, sso)
    assert finish(client, params).headers["location"] == "/login?error=sso"
    assert "sensitive provider body" not in caplog.text and params["code"] not in caplog.text


@pytest.mark.parametrize(
    "path",
    [
        "https://evil.example",
        "//evil.example",
        "/\\evil.example",
        "/%2f%2fevil.example",
        "/\nevil.example",
    ],
)
def test_redirects_are_local(client, sso, path):
    assert finish(client, start(client, sso, next_path=path)).headers["location"] == "/"


def test_sso_users_cannot_use_local_security_or_be_locally_promoted(client, db_session, sso):
    finish(
        client,
        start(client, sso, {"resource_access": {"cloudscope": {"roles": ["cloudscope-admin"]}}}),
    )
    user = client.get("/api/auth/me").json()
    assert (
        client.post(
            "/api/auth/login",
            headers=CSRF,
            json={"username": user["username"], "password": PASSWORD},
        ).status_code
        == 401
    )
    for path, body in [
        ("password", {"current_password": PASSWORD, "new_password": PASSWORD}),
        ("mfa/setup", {}),
        ("mfa/enable", {"code": "123456"}),
        ("mfa/disable", {"code": "123456", "password": PASSWORD}),
        ("mfa/verify-login", {"code": "123456"}),
    ]:
        assert client.post("/api/auth/" + path, headers=CSRF, json=body).status_code == 403
    for body in ({"password": PASSWORD}, {"is_admin": False}):
        assert client.patch(f"/api/users/{user['id']}", headers=CSRF, json=body).status_code == 403
    assert client.post(f"/api/users/{user['id']}/reset-mfa", headers=CSRF).status_code == 403
    stored = db_session.get(User, user["id"])
    stored.is_active = False
    db_session.commit()
    client.cookies.clear()
    assert finish(client, start(client, sso)).headers["location"] == "/login?error=not-authorized"


def test_local_admin_only_and_config(client, db_session, user, sso):
    assert client.get("/api/auth/config").json() == {
        "local_login": True,
        "sso": {"enabled": True, "label": "Sign in with Keycloak"},
    }
    assert (
        client.post(
            "/api/auth/login", headers=CSRF, json={"username": "tester", "password": PASSWORD}
        ).status_code
        == 401
    )
    user.is_admin = True
    db_session.commit()
    assert (
        client.post(
            "/api/auth/login", headers=CSRF, json={"username": "tester", "password": PASSWORD}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/users", headers=CSRF, json={"username": "local", "password": PASSWORD}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/users",
            headers=CSRF,
            json={"username": "local", "password": PASSWORD, "is_admin": True},
        ).status_code
        == 201
    )
    assert (
        client.patch(f"/api/users/{user.id}", headers=CSRF, json={"is_admin": False}).status_code
        == 403
    )
    assert client.post("/api/auth/logout", headers=CSRF).json() == {}


def test_callback_uses_password_rate_limit(client, sso):
    for _ in range(20):
        client.post(
            "/api/auth/login", headers=CSRF, json={"username": "unknown", "password": PASSWORD}
        )
    assert finish(client, start(client, sso)).status_code == 429
    assert COOKIE_NAME not in client.cookies


@pytest.mark.parametrize("path", ["/api/auth/oidc/callback", "/api/auth/oidc/callback/"])
def test_callback_logs_strip_query(path):
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("10.0.0.1", "GET", path + "?code=secret&state=secret", "1.1", 302),
        None,
    )
    assert CallbackLogFilter().filter(record)
    assert "secret" not in record.getMessage()
    assert safe_next("/nat-gateways?page=2") == "/nat-gateways?page=2"


def test_signature_verification_and_unknown_key_fail_closed(client, sso):
    # Prime the cached public key, then sign with an unrelated private key using the same kid.
    service = client.app.state.oidc
    service.signing_key(sso.kid)
    sso.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert finish(client, start(client, sso)).headers["location"] == "/login?error=sso"
    assert COOKIE_NAME not in client.cookies


def test_state_can_be_consumed_on_another_pod_only_once(client, sso):
    params = start(client, sso)
    first = client.app.state.oidc
    other = OIDCService(first.auth, first.settings, first.client)
    client.app.state.oidc = other
    assert finish(client, params).headers["location"] == "/nat-gateways"
    client.app.state.oidc = first
    assert finish(client, params).headers["location"] == "/login?error=sso"


def test_sso_off_retains_local_login_and_disables_oidc_routes(client, user):
    assert client.get("/api/auth/config").json()["sso"]["enabled"] is False
    assert client.get("/api/auth/oidc/login").status_code == 404
    assert client.get("/api/auth/oidc/callback").status_code == 404
    assert (
        client.post(
            "/api/auth/login", headers=CSRF, json={"username": user.username, "password": PASSWORD}
        ).status_code
        == 200
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"public_url": ""},
        {"oidc_client_secret": ""},
        {"oidc_issuer": "https://user:password@idp.example.com"},
        {"public_url": "https://app.example.com/path"},
        {"public_url": "//app.example.com"},
        {"oidc_issuer": "https://idp.example.com?query=1"},
    ],
)
def test_incomplete_or_unsafe_oidc_config_rejected(overrides):
    from pydantic import ValidationError

    values = dict(
        database_url="postgresql+psycopg://localhost/test",
        secret_key=Fernet.generate_key().decode(),
        oidc_issuer=ISSUER,
        oidc_client_secret="fake-client-secret",
        public_url=PUBLIC,
    )
    with pytest.raises(ValidationError):
        Settings(**(values | overrides))
