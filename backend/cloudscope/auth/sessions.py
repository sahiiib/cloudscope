"""Database-backed sessions and password login; only token hashes are persisted."""

import hashlib
import json
import logging
import secrets
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Lock
from time import monotonic

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from cloudscope.auth.passwords import hash_password, verify_and_rehash, verify_password
from cloudscope.db.models import User, UserSession

COOKIE_NAME = "cloudscope_session"
HALF_SESSION_TTL = timedelta(minutes=5)
logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(UTC)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class LoginRateLimiter:
    """Per-pod sliding window. Expired IP entries are discarded on every attempt."""

    def __init__(self, clock: Callable[[], float] = monotonic) -> None:
        self.clock = clock
        self.attempts: dict[str, deque[float]] = {}
        self.lock = Lock()

    def allow(self, ip: str) -> bool:
        with self.lock:
            now = self.clock()
            for key in list(self.attempts):
                attempts = self.attempts[key]
                while attempts and attempts[0] <= now - 60:
                    attempts.popleft()
                if not attempts:
                    del self.attempts[key]
            attempts = self.attempts.setdefault(ip, deque())
            if len(attempts) >= 20:
                return False
            attempts.append(now)
            return True


@dataclass(frozen=True)
class LoginResult:
    token: str
    mfa_required: bool
    max_age: int


class AuthService:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        ttl_hours: int = 12,
        max_age_days: int = 7,
        cookie_secure: bool = True,
        clock: Callable[[], datetime] = utc_now,
        limiter: LoginRateLimiter | None = None,
    ) -> None:
        if ttl_hours <= 0 or max_age_days <= 0:
            raise ValueError("Session lifetime must be positive")
        self.sessions = sessions
        self.ttl = timedelta(hours=ttl_hours)
        self.max_age = timedelta(days=max_age_days)
        self.cookie_secure = cookie_secure
        self.clock = clock
        self.limiter = limiter or LoginRateLimiter()
        # Unknown users also perform an Argon2 verification, without a static secret.
        self.dummy_hash = hash_password(secrets.token_urlsafe(32))

    def login(
        self, username: str, password: str, ip: str, user_agent: str, old_token: str | None
    ) -> LoginResult:
        if not self.limiter.allow(ip):
            self._audit(username, ip, "rate_limited")
            raise HTTPException(429, "Too many login attempts")
        result: LoginResult | None = None
        with self.sessions.begin() as session:
            user = session.scalar(select(User).where(User.username == username).with_for_update())
            now = self.clock()
            if (
                user is None
                or not user.is_active
                or (user.locked_until is not None and user.locked_until > now)
            ):
                verify_password(password, self.dummy_hash)
            else:
                if user.locked_until is not None:
                    user.failed_logins = 0
                    user.locked_until = None
                valid, replacement = verify_and_rehash(password, user.password_hash)
                if not valid:
                    user.failed_logins += 1
                    if user.failed_logins >= 5:
                        user.locked_until = now + timedelta(minutes=15)
                else:
                    if replacement is not None:
                        user.password_hash = replacement
                    user.failed_logins = 0
                    user.locked_until = None
                    if not user.mfa_enabled:
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
                    ttl = HALF_SESSION_TTL if user.mfa_enabled else min(self.ttl, self.max_age)
                    session.add(
                        UserSession(
                            id_hash=token_hash(token),
                            user_id=user.id,
                            mfa_passed=not user.mfa_enabled,
                            created_at=now,
                            expires_at=now + ttl,
                            last_seen_at=now,
                            ip=ip,
                            user_agent=user_agent,
                        )
                    )
                    result = LoginResult(token, user.mfa_enabled, int(ttl.total_seconds()))
        # Raise after committing so failed-login counters and lockouts persist.
        self._audit(
            username,
            ip,
            "invalid_credentials"
            if result is None
            else "mfa_pending"
            if result.mfa_required
            else "success",
        )
        if result is None:
            raise HTTPException(401, "Invalid username or password")
        return result

    def _lookup(
        self, session: Session, token: str | None, *, require_mfa: bool = True
    ) -> tuple[User, UserSession]:
        if not token or len(token) > 128:
            raise HTTPException(401, "Authentication required")
        stored = session.get(UserSession, token_hash(token))
        if stored is None:
            raise HTTPException(401, "Authentication required")
        # Serialize with login/password changes, then re-read the session in case
        # another transaction revoked it while this request waited for the user.
        user = session.scalar(select(User).where(User.id == stored.user_id).with_for_update())
        stored = session.get(UserSession, token_hash(token), populate_existing=True)
        if (
            user is None
            or not user.is_active
            or stored is None
            or stored.expires_at <= self.clock()
            or stored.created_at + self.max_age <= self.clock()
        ):
            raise HTTPException(401, "Authentication required")
        if require_mfa and not stored.mfa_passed:
            raise HTTPException(401, "MFA verification required")
        return user, stored

    def authenticate(self, token: str | None) -> tuple[User, datetime]:
        with self.sessions.begin() as session:
            user, stored = self._lookup(session, token)
            now = self.clock()
            stored.last_seen_at = now
            stored.expires_at = min(now + self.ttl, stored.created_at + self.max_age)
            session.expunge(user)
            return user, stored.expires_at

    def logout(self, token: str | None) -> None:
        with self.sessions.begin() as session:
            _, stored = self._lookup(session, token, require_mfa=False)
            session.delete(stored)

    def change_password(self, token: str | None, current: str, new: str) -> None:
        with self.sessions.begin() as session:
            user, _ = self._lookup(session, token)
            if not verify_password(current, user.password_hash):
                raise HTTPException(401, "Invalid current password")
            user.password_hash = hash_password(new)
            # Password changes revoke every session, including the current cookie.
            session.execute(delete(UserSession).where(UserSession.user_id == user.id))

    @staticmethod
    def _audit(username: str, ip: str, result: str) -> None:
        logger.info(
            "event=login username=%s ip=%s result=%s", json.dumps(username), json.dumps(ip), result
        )
