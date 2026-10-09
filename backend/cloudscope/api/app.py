"""FastAPI application factory."""

import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, cast

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.base import RequestResponseEndpoint

from cloudscope.api.routes.auth import router as auth_router
from cloudscope.api.routes.auth import set_session_cookie
from cloudscope.auth.deps import require_admin
from cloudscope.auth.sessions import COOKIE_NAME, AuthService, utc_now
from cloudscope.config import Settings
from cloudscope.db.models import User
from cloudscope.db.session import create_db_engine, create_session_factory


def create_app(
    engine: Engine | None = None,
    *,
    settings: Settings | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> FastAPI:
    """Create an API; an injected engine remains owned by the caller."""
    database_engine = engine

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        nonlocal database_engine
        if engine is None:
            url = (
                settings.database_url.get_secret_value()
                if settings
                else os.environ.get("CLOUDSCOPE_DATABASE_URL")
            )
            if url:
                try:
                    database_engine = create_db_engine(url)
                except (SQLAlchemyError, ValueError):
                    # Keep liveness available; readiness reports misconfiguration.
                    database_engine = None
        runtime_settings = settings
        if runtime_settings is None:
            try:
                runtime_settings = Settings()  # type: ignore[call-arg]
            except ValidationError:
                runtime_settings = None
        app.state.auth = None
        if database_engine is not None and runtime_settings is not None:
            app.state.auth = AuthService(
                create_session_factory(database_engine),
                ttl_hours=runtime_settings.session_ttl_hours,
                cookie_secure=runtime_settings.cookie_secure,
                clock=clock,
            )
        try:
            yield
        finally:
            if engine is None and database_engine is not None:
                database_engine.dispose()
                database_engine = None

    app = FastAPI(
        title="Cloudscope", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )
    app.include_router(auth_router)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # FastAPI normally echoes invalid inputs; these may be plaintext passwords.
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {key: value for key, value in error.items() if key in {"loc", "msg", "type"}}
                    for error in exc.errors()
                ]
            },
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": "Database unavailable"})

    @app.middleware("http")
    async def refresh_cookie(request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        if getattr(request.state, "refresh_session", False) and response.status_code < 400:
            auth = cast(AuthService, request.app.state.auth)
            token = request.cookies.get(COOKIE_NAME)
            if token and "set-cookie" not in response.headers:
                set_session_cookie(response, token, auth, int(auth.ttl.total_seconds()))
        return response

    @app.get("/api/docs", include_in_schema=False)
    def docs(user: Annotated[User, Depends(require_admin)]) -> Response:
        return get_swagger_ui_html(openapi_url="/api/openapi.json", title="Cloudscope API")

    @app.get("/api/openapi.json", include_in_schema=False)
    def openapi(user: Annotated[User, Depends(require_admin)]) -> JSONResponse:
        return JSONResponse(app.openapi())

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> dict[str, str]:
        if database_engine is None:
            raise HTTPException(status_code=503, detail="Database unavailable")
        try:
            with database_engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except SQLAlchemyError:
            raise HTTPException(status_code=503, detail="Database unavailable") from None
        return {"status": "ok"}

    return app
