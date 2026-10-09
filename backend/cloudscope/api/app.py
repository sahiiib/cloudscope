"""FastAPI application factory."""

from fastapi import FastAPI


def create_app() -> FastAPI:
    """Create an independent API application."""
    app = FastAPI(title="Cloudscope")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> dict[str, str]:
        # T-005 adds the database readiness check.
        return {"status": "ok"}

    return app
