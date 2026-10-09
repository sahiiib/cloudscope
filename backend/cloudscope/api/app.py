"""FastAPI application factory."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from cloudscope.db.session import create_db_engine


def create_app(engine: Engine | None = None) -> FastAPI:
    """Create an API; an injected engine remains owned by the caller."""
    database_engine = engine

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        nonlocal database_engine
        if engine is None:
            url = os.environ.get("CLOUDSCOPE_DATABASE_URL")
            if url:
                try:
                    database_engine = create_db_engine(url)
                except (SQLAlchemyError, ValueError):
                    # Keep liveness available; readiness reports misconfiguration.
                    database_engine = None
        try:
            yield
        finally:
            if engine is None and database_engine is not None:
                database_engine.dispose()
                database_engine = None

    app = FastAPI(title="Cloudscope", lifespan=lifespan)

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
