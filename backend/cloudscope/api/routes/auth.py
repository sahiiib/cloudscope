"""Password login, current-user information, logout and password changes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from cloudscope.auth.deps import current_user, get_auth, require_csrf
from cloudscope.auth.sessions import COOKIE_NAME, AuthService
from cloudscope.db.models import User

router = APIRouter(prefix="/api/auth", tags=["auth"])
Auth = Annotated[AuthService, Depends(get_auth)]


class LoginBody(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    username: str = Field(max_length=256)
    password: SecretStr


class PasswordBody(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    current_password: SecretStr
    new_password: SecretStr = Field(min_length=12)


class MeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    is_admin: bool
    mfa_enabled: bool


def set_session_cookie(response: Response, token: str, auth: AuthService, max_age: int) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=max_age,
        httponly=True,
        secure=auth.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response, auth: AuthService) -> None:
    response.delete_cookie(
        COOKIE_NAME, httponly=True, secure=auth.cookie_secure, samesite="lax", path="/"
    )


@router.post("/login", dependencies=[Depends(require_csrf)])
def login(body: LoginBody, request: Request, response: Response, auth: Auth) -> dict[str, bool]:
    result = auth.login(
        body.username,
        body.password.get_secret_value(),
        request.client.host if request.client else "unknown",
        request.headers.get("user-agent", "")[:1024],
        request.cookies.get(COOKIE_NAME),
    )
    set_session_cookie(response, result.token, auth, result.max_age)
    return {"mfa_required": result.mfa_required}


@router.post("/logout", status_code=204, dependencies=[Depends(require_csrf)])
def logout(request: Request, auth: Auth) -> Response:
    auth.logout(request.cookies.get(COOKIE_NAME))
    response = Response(status_code=204)
    clear_session_cookie(response, auth)
    return response


@router.get("/me", response_model=MeResponse)
def me(user: Annotated[User, Depends(current_user)]) -> User:
    return user


@router.post("/password", status_code=204, dependencies=[Depends(require_csrf)])
def password(body: PasswordBody, request: Request, auth: Auth) -> Response:
    auth.change_password(
        request.cookies.get(COOKIE_NAME),
        body.current_password.get_secret_value(),
        body.new_password.get_secret_value(),
    )
    response = Response(status_code=204)
    clear_session_cookie(response, auth)
    return response
