"""Argon2id passwords with safe verification and optional rehash after login."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.low_level import Type

MIN_PASSWORD_LENGTH = 12
_hasher = PasswordHasher(type=Type.ID)


def hash_password(password: str) -> str:
    """Hash a new password using argon2-cffi defaults and a fresh random salt."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must contain at least {MIN_PASSWORD_LENGTH} characters")
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Reject mismatched or malformed hashes without exposing verifier errors."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def verify_and_rehash(password: str, password_hash: str) -> tuple[bool, str | None]:
    """Return (valid, replacement_hash); login callers persist a replacement if present.

    Length policy applies to new/changed passwords. Verification and rehash must
    still work for existing passwords if the creation policy changes later.
    """
    if not verify_password(password, password_hash):
        return False, None
    if _hasher.check_needs_rehash(password_hash):
        return True, _hasher.hash(password)
    return True, None
