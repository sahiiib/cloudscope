"""Reusable authentication, authorization and CSRF dependencies."""

from typing import Annotated, cast

from fastapi import Depends, HTTPException, Request

from cloudscope.auth.sessions import COOKIE_NAME, AuthService
from cloudscope.db.models import User


def get_auth(request: Request) -> AuthService:
    service = cast(AuthService | None, getattr(request.app.state, "auth", None))
    if service is None:
        raise HTTPException(503, "Authentication unavailable")
    return service


def require_csrf(request: Request) -> None:
    if request.headers.get("X-Requested-With") != "cloudscope":
        raise HTTPException(403, "Missing CSRF header")


def current_user(request: Request, auth: Annotated[AuthService, Depends(get_auth)]) -> User:
    user = auth.authenticate(request.cookies.get(COOKIE_NAME))
    request.state.refresh_session = True
    return user


def require_admin(user: Annotated[User, Depends(current_user)]) -> User:
    if not user.is_admin:
        raise HTTPException(403, "Admin access required")
    return user
