"""Server-side OIDC code flow. Tokens and authorization codes are never persisted."""

import base64
import hashlib
import json
import logging
import secrets
from datetime import timedelta
from threading import RLock
from time import monotonic
from typing import Any
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

import httpx
import jwt
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from cloudscope.auth.sessions import AuthService, LoginResult, token_hash
from cloudscope.config import Settings
from cloudscope.db.models import OIDCLoginState, User, UserSession

COOKIE = "cloudscope_oidc"
TTL = timedelta(minutes=10)
logger = logging.getLogger(__name__)


class OIDCError(Exception):
    pass


class NotAuthorized(OIDCError):
    pass


class CallbackLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and len(record.args) == 5:
            args = list(record.args)
            if isinstance(args[2], str) and args[2].startswith("/api/auth/oidc/"):
                args[2] = args[2].split("?", 1)[0]
                record.args = tuple(args)
        return True


def safe_next(value: str) -> str:
    decoded = unquote(value)
    if (
        not value.startswith("/")
        or value.startswith("//")
        or decoded.startswith("//")
        or "\\" in decoded
        or any(ord(c) < 32 or ord(c) == 127 for c in decoded)
    ):
        return "/"
    return value


def with_query(url: str, values: dict[str, str]) -> str:
    parsed = urlsplit(url)
    query = dict(parse_qsl(parsed.query))
    query.update(values)
    return urlunsplit(parsed._replace(query=urlencode(query)))


class OIDCService:
    def __init__(
        self, auth: AuthService, settings: Settings, client: httpx.Client | None = None
    ) -> None:
        self.auth, self.settings = auth, settings
        self.client = client or httpx.Client(timeout=10, follow_redirects=False)
        self.lock = RLock()
        self.metadata: dict[str, Any] = {}
        self.keys: list[dict[str, Any]] = []
        self.metadata_until = self.keys_until = 0.0

    @property
    def callback_url(self) -> str:
        return self.settings.public_url.rstrip("/") + "/api/auth/oidc/callback"

    def endpoint(self, value: object) -> str:
        if not isinstance(value, str):
            raise OIDCError()
        parsed = urlsplit(value)
        issuer = urlsplit(self.settings.oidc_issuer)
        if (
            not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
            or parsed.scheme not in ("http", "https")
            or (
                parsed.scheme == "http"
                and (issuer.scheme != "http" or parsed.netloc != issuer.netloc)
            )
        ):
            raise OIDCError()
        return value

    def discovery(self) -> dict[str, Any]:
        with self.lock:
            if monotonic() >= self.metadata_until:
                response = self.client.get(
                    self.settings.oidc_issuer.rstrip("/") + "/.well-known/openid-configuration"
                )
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict) or data.get("issuer") != self.settings.oidc_issuer:
                    raise OIDCError()
                for field in (
                    "authorization_endpoint",
                    "token_endpoint",
                    "jwks_uri",
                    "end_session_endpoint",
                ):
                    self.endpoint(data.get(field))
                self.metadata = data
                self.metadata_until = monotonic() + 300
            return self.metadata

    def signing_key(self, kid: str) -> jwt.PyJWK:
        with self.lock:
            refreshed = False
            if monotonic() >= self.keys_until:
                self.refresh_keys()
                refreshed = True
            matches = [key for key in self.keys if key.get("kid") == kid]
            if not matches and not refreshed:
                self.refresh_keys()
                matches = [key for key in self.keys if key.get("kid") == kid]
            if (
                len(matches) != 1
                or matches[0].get("kty") != "RSA"
                or matches[0].get("use", "sig") != "sig"
                or matches[0].get("alg", "RS256") != "RS256"
            ):
                raise OIDCError()
            return jwt.PyJWK.from_dict(matches[0], algorithm="RS256")

    def refresh_keys(self) -> None:
        response = self.client.get(self.endpoint(self.discovery()["jwks_uri"]))
        response.raise_for_status()
        data = response.json()
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("keys"), list)
            or any(not isinstance(key, dict) for key in data["keys"])
        ):
            raise OIDCError()
        self.keys = data["keys"]
        self.keys_until = monotonic() + 300

    def begin(self, next_path: str, old_cookie: str | None) -> tuple[str, str]:
        authorize = self.endpoint(self.discovery()["authorization_endpoint"])
        cookie, state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(4))
        now = self.auth.clock()
        with self.auth.sessions.begin() as session:
            session.execute(delete(OIDCLoginState).where(OIDCLoginState.created_at <= now - TTL))
            if old_cookie:
                session.execute(
                    delete(OIDCLoginState).where(OIDCLoginState.id_hash == token_hash(old_cookie))
                )
            session.add(
                OIDCLoginState(
                    id_hash=token_hash(cookie),
                    state=state,
                    nonce=nonce,
                    code_verifier=verifier,
                    next_path=safe_next(next_path),
                    created_at=now,
                )
            )
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        return cookie, with_query(
            authorize,
            {
                "client_id": self.settings.oidc_client_id,
                "redirect_uri": self.callback_url,
                "response_type": "code",
                "scope": "openid profile",
                "state": state,
                "nonce": nonce,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )

    def consume(self, cookie: str | None, state: str) -> dict[str, str]:
        if not cookie or len(cookie) > 128:
            raise OIDCError()
        with self.auth.sessions.begin() as session:
            row = session.execute(
                delete(OIDCLoginState)
                .where(OIDCLoginState.id_hash == token_hash(cookie))
                .returning(OIDCLoginState)
            ).scalar_one_or_none()
            data = (
                None
                if row is None
                else {
                    "state": row.state,
                    "nonce": row.nonce,
                    "verifier": row.code_verifier,
                    "next": row.next_path,
                }
            )
            fresh = row is not None and row.created_at > self.auth.clock() - TTL
        if not data or not fresh or not secrets.compare_digest(data["state"], state):
            raise OIDCError()
        return data

    def complete(
        self, data: dict[str, str], code: str, ip: str, user_agent: str, old_token: str | None
    ) -> tuple[LoginResult, str]:
        response = self.client.post(
            self.endpoint(self.discovery()["token_endpoint"]),
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.callback_url,
                "client_id": self.settings.oidc_client_id,
                "client_secret": self.settings.oidc_client_secret.get_secret_value(),
                "code_verifier": data["verifier"],
            },
        )
        response.raise_for_status()
        encoded = response.json()["id_token"]
        header = jwt.get_unverified_header(encoded)
        if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
            raise OIDCError()
        claims = jwt.decode(
            encoded,
            self.signing_key(header["kid"]).key,
            algorithms=["RS256"],
            audience=self.settings.oidc_client_id,
            issuer=self.settings.oidc_issuer,
            leeway=60,
            options={"require": ["iss", "sub", "aud", "exp", "iat", "nonce"]},
        )
        if not isinstance(claims["nonce"], str) or not secrets.compare_digest(
            claims["nonce"], data["nonce"]
        ):
            raise OIDCError()
        if claims.get("azp", self.settings.oidc_client_id) != self.settings.oidc_client_id or (
            isinstance(claims["aud"], list) and len(claims["aud"]) > 1 and "azp" not in claims
        ):
            raise OIDCError()
        sub, username = claims["sub"], claims.get("preferred_username")
        if (
            not isinstance(sub, str)
            or not sub
            or not isinstance(username, str)
            or not username.strip()
            or len(username) > 256
        ):
            raise OIDCError()
        roles = (
            claims.get("resource_access", {}).get(self.settings.oidc_client_id, {}).get("roles", [])
        )
        if not isinstance(roles, list) or not any(
            role in roles for role in ("cloudscope-user", "cloudscope-admin")
        ):
            self.audit(username, sub, ip, "not_authorized")
            raise NotAuthorized()
        now = self.auth.clock()
        with self.auth.sessions.begin() as session:
            identity = (User.oidc_issuer == self.settings.oidc_issuer, User.oidc_subject == sub)
            user = session.scalar(select(User).where(*identity).with_for_update())
            if user is None:
                # Unique identity and username constraints serialize competing first logins.
                for attempt in range(100):
                    name = (
                        username
                        if attempt == 0
                        else username + ("@sso" if attempt == 1 else f"@sso{attempt}")
                    )
                    session.execute(
                        insert(User)
                        .values(
                            username=name,
                            oidc_issuer=self.settings.oidc_issuer,
                            oidc_subject=sub,
                            password_hash=None,
                        )
                        .on_conflict_do_nothing()
                    )
                    user = session.scalar(select(User).where(*identity).with_for_update())
                    if user is not None:
                        break
            if user is None or not user.is_active:
                self.audit(username, sub, ip, "not_authorized")
                raise NotAuthorized()
            user.is_admin = "cloudscope-admin" in roles
            user.last_login_at = now
            session.execute(
                delete(UserSession).where(
                    UserSession.user_id == user.id, UserSession.expires_at <= now
                )
            )
            if old_token:
                session.execute(
                    delete(UserSession).where(UserSession.id_hash == token_hash(old_token))
                )
            token = secrets.token_urlsafe(32)
            ttl = min(self.auth.ttl, self.auth.max_age)
            session.add(
                UserSession(
                    id_hash=token_hash(token),
                    user_id=user.id,
                    mfa_passed=True,
                    created_at=now,
                    expires_at=now + ttl,
                    last_seen_at=now,
                    ip=ip,
                    user_agent=user_agent,
                )
            )
        self.audit(username, sub, ip, "success")
        return LoginResult(token, False, int(ttl.total_seconds())), safe_next(data["next"])

    def logout_url(self) -> str:
        root = self.settings.public_url.rstrip("/") + "/"
        try:
            return with_query(
                self.endpoint(self.discovery()["end_session_endpoint"]),
                {"client_id": self.settings.oidc_client_id, "post_logout_redirect_uri": root},
            )
        except Exception:
            return root

    @staticmethod
    def audit(username: str, sub: str, ip: str, result: str) -> None:
        logger.info(
            "event=sso_login username=%s sub=%s ip=%s result=%s",
            json.dumps(username),
            json.dumps(sub),
            json.dumps(ip),
            result,
        )
