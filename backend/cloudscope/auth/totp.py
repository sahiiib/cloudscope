"""Encrypted TOTP enrollment and atomic, replay-protected MFA verification."""

import hashlib
import io
import re
import secrets
from datetime import datetime

import pyotp
import segno
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from sqlalchemy import delete
from sqlalchemy.orm import Session

from cloudscope.auth.passwords import verify_password
from cloudscope.auth.sessions import AuthService, LoginResult, token_hash
from cloudscope.db.models import User, UserSession


class MFAService:
    def __init__(self, auth: AuthService, cipher: Fernet) -> None:
        self.auth = auth
        self.cipher = cipher

    def setup(self, token: str | None) -> dict[str, str]:
        with self.auth.sessions.begin() as session:
            user, _ = self.auth.lookup_session(session, token)
            if user.mfa_enabled:
                raise HTTPException(409, "MFA already enabled")
            secret = pyotp.random_base32()
            user.totp_secret_enc = self.cipher.encrypt(secret.encode()).decode()
            user.totp_last_used_step = None
            uri = pyotp.TOTP(secret, issuer="cloudscope", name=user.username).provisioning_uri()
            svg = io.BytesIO()
            segno.make(uri, micro=False).save(svg, kind="svg", scale=4, xmldecl=False)
            return {"otpauth_uri": uri, "qr_svg": svg.getvalue().decode()}

    def _consume(self, user: User, code: str, now: datetime) -> bool:
        # Caller holds the user row lock, serializing reuse across sessions/pods.
        if not user.totp_secret_enc:
            raise HTTPException(409, "MFA setup required")
        if re.fullmatch(r"[0-9]{6}", code) is None:
            return False
        try:
            secret = self.cipher.decrypt(user.totp_secret_enc.encode()).decode()
            totp = pyotp.TOTP(secret, digits=6, interval=30, digest=hashlib.sha1)
            step = totp.timecode(now)
            for candidate in (step - 1, step, step + 1):
                if candidate < 0:
                    continue
                if secrets.compare_digest(totp.generate_otp(candidate), code):
                    if (
                        user.totp_last_used_step is not None
                        and candidate <= user.totp_last_used_step
                    ):
                        return False
                    user.totp_last_used_step = candidate
                    return True
        except (InvalidToken, ValueError, UnicodeError):
            raise HTTPException(503, "MFA unavailable") from None
        return False

    @staticmethod
    def _revoke_other_sessions(session: Session, user: User, stored: UserSession) -> None:
        session.execute(
            delete(UserSession).where(
                UserSession.user_id == user.id, UserSession.id_hash != stored.id_hash
            )
        )

    def enable(self, token: str | None, code: str) -> None:
        with self.auth.sessions.begin() as session:
            user, stored = self.auth.lookup_session(session, token)
            if user.mfa_enabled:
                raise HTTPException(409, "MFA already enabled")
            if not self._consume(user, code, self.auth.clock()):
                raise HTTPException(401, "Invalid MFA code")
            user.mfa_enabled = True
            self._revoke_other_sessions(session, user, stored)

    def disable(self, token: str | None, password: str, code: str) -> None:
        with self.auth.sessions.begin() as session:
            user, stored = self.auth.lookup_session(session, token)
            if not user.mfa_enabled:
                raise HTTPException(409, "MFA is not enabled")
            if not verify_password(password, user.password_hash) or not self._consume(
                user, code, self.auth.clock()
            ):
                raise HTTPException(401, "Invalid password or MFA code")
            user.mfa_enabled = False
            user.totp_secret_enc = None
            user.totp_last_used_step = None
            self._revoke_other_sessions(session, user, stored)

    def verify_login(self, token: str | None, code: str) -> LoginResult:
        result: LoginResult | None = None
        with self.auth.sessions.begin() as session:
            user, stored = self.auth.lookup_session(session, token, require_mfa=False)
            if stored.mfa_passed:
                raise HTTPException(409, "MFA already verified")
            if not user.mfa_enabled:
                raise HTTPException(401, "Authentication required")
            now = self.auth.clock()
            if self._consume(user, code, now):
                new_token = secrets.token_urlsafe(32)
                ttl = min(self.auth.ttl, self.auth.max_age)
                session.add(
                    UserSession(
                        id_hash=token_hash(new_token),
                        user_id=user.id,
                        mfa_passed=True,
                        created_at=now,
                        last_seen_at=now,
                        expires_at=now + ttl,
                        ip=stored.ip,
                        user_agent=stored.user_agent,
                    )
                )
                session.delete(stored)
                user.last_login_at = now
                result = LoginResult(new_token, False, int(ttl.total_seconds()))
            else:
                stored.mfa_failures += 1
                if stored.mfa_failures >= 5:
                    session.delete(stored)
        self.auth._audit(user.username, stored.ip, "mfa_success" if result else "mfa_invalid")
        # Commit failure counters/deletion before returning an error.
        if result is None:
            raise HTTPException(401, "Invalid MFA code")
        return result
