"""Administrator user management with transactional session revocation."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cloudscope.api.routes.auth import Auth, clear_session_cookie
from cloudscope.auth.deps import require_admin, require_csrf
from cloudscope.auth.passwords import hash_password
from cloudscope.auth.sessions import COOKIE_NAME, AuthService
from cloudscope.db.models import User, UserSession

router = APIRouter(prefix="/api/users", dependencies=[Depends(require_admin)])


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    is_admin: bool
    is_active: bool
    mfa_enabled: bool
    created_at: datetime
    last_login_at: datetime | None


class CreateUserBody(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    username: str = Field(min_length=1, max_length=256)
    password: SecretStr = Field(min_length=12)
    is_admin: bool = False

    @field_validator("username")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip() or value != value.strip():
            raise ValueError("Username cannot be blank or have surrounding whitespace")
        return value


class UpdateUserBody(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    is_active: bool | None = None
    is_admin: bool | None = None
    password: SecretStr | None = Field(default=None, min_length=12)

    @field_validator("is_active", "is_admin", "password")
    @classmethod
    def not_null(cls, value: bool | SecretStr | None) -> bool | SecretStr:
        if value is None:
            raise ValueError("Supplied fields cannot be null")
        return value


@contextmanager
def mutation(auth: AuthService, request: Request) -> Iterator[tuple[Session, User]]:
    with auth.sessions.begin() as session:
        # Serialize admin mutations, including the last-admin check. Reauthenticate
        # inside this transaction so a concurrent demotion/revocation takes effect.
        session.execute(text("SELECT pg_advisory_xact_lock(1129530193)"))
        actor, _ = auth.lookup_session(session, request.cookies.get(COOKIE_NAME))
        if not actor.is_admin:
            raise HTTPException(403, "Admin access required")
        yield session, actor


def target_user(session: Session, id: int) -> User:
    user = session.scalar(select(User).where(User.id == id).with_for_update())
    if user is None:
        raise HTTPException(404, "User not found")
    return user


def revoke(session: Session, id: int) -> None:
    session.execute(delete(UserSession).where(UserSession.user_id == id))


@router.get("", response_model=list[UserResponse])
def users(auth: Auth) -> list[UserResponse]:
    with auth.sessions() as session:
        return [
            UserResponse.model_validate(user)
            for user in session.scalars(select(User).order_by(User.username, User.id))
        ]


@router.post("", status_code=201, response_model=UserResponse, dependencies=[Depends(require_csrf)])
def create_user(body: CreateUserBody, request: Request, auth: Auth) -> UserResponse:
    try:
        with mutation(auth, request) as (session, _):
            user = User(
                username=body.username,
                password_hash=hash_password(body.password.get_secret_value()),
                is_admin=body.is_admin,
            )
            session.add(user)
            session.flush()
            result = UserResponse.model_validate(user)
        return result
    except IntegrityError:
        raise HTTPException(409, "Username already exists") from None


@router.patch("/{id}", response_model=UserResponse, dependencies=[Depends(require_csrf)])
def update_user(
    id: int, body: UpdateUserBody, request: Request, response: Response, auth: Auth
) -> UserResponse:
    with mutation(auth, request) as (session, actor):
        user = target_user(session, id)
        if user.is_admin and user.is_active and (body.is_active is False or body.is_admin is False):
            others = session.scalar(
                select(func.count())
                .select_from(User)
                .where(User.id != id, User.is_active.is_(True), User.is_admin.is_(True))
            )
            if not others:
                raise HTTPException(409, "Cannot remove the last active administrator")
        changed = False
        for field in ("is_active", "is_admin"):
            value = getattr(body, field)
            if value is not None and value != getattr(user, field):
                setattr(user, field, value)
                changed = True
        if body.password is not None:
            user.password_hash = hash_password(body.password.get_secret_value())
            user.failed_logins = 0
            user.locked_until = None
            changed = True
        if changed:
            revoke(session, id)
            if actor.id == id:
                clear_session_cookie(response, auth)
        session.flush()
        return UserResponse.model_validate(user)


@router.post("/{id}/reset-mfa", status_code=204, dependencies=[Depends(require_csrf)])
def reset_mfa(id: int, request: Request, auth: Auth) -> Response:
    response = Response(status_code=204)
    with mutation(auth, request) as (session, actor):
        user = target_user(session, id)
        user.mfa_enabled = False
        user.totp_secret_enc = None
        user.totp_last_used_step = None
        revoke(session, id)
        if actor.id == id:
            clear_session_cookie(response, auth)
    return response
