"""Extract diagnostic identifiers without exposing SDK messages or payloads."""

import re

from botocore.exceptions import ClientError  # type: ignore[import-untyped]
from Tea.exceptions import TeaException  # type: ignore[import-untyped]


def describe_error(exc: Exception) -> str:
    """Return an SDK error code, otherwise the exception class, never its text."""
    if isinstance(exc, AssumeRoleError):
        return exc.code
    code: object = None
    if isinstance(exc, ClientError):
        error = exc.response.get("Error")
        if isinstance(error, dict):
            code = error.get("Code")
    elif isinstance(exc, TeaException):
        code = exc.code
    # Codes are identifiers, not free text. Reject malformed codes so they cannot
    # inject log lines; cap the identifier to leave room for the phase prefix.
    if isinstance(code, str) and re.fullmatch(r"[A-Za-z0-9_.:-]+", code):
        return code[:160]
    return type(exc).__name__[:160]


class AssumeRoleError(Exception):
    """Mark the STS phase without exposing sensitive SDK exception payloads."""

    def __init__(self, error: Exception) -> None:
        self.code = describe_error(error)
        super().__init__(self.code)


def log_account_id(value: str) -> str:
    """Keep IDs unquoted, escaping any unsafe characters from legacy file entries."""
    return re.sub(r"[^A-Za-z0-9_.:-]", lambda match: f"\\u{ord(match[0]):04x}", value)
