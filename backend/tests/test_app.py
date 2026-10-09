from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.exc import OperationalError

from cloudscope.api.app import create_app


def test_liveness_without_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLOUDSCOPE_DATABASE_URL", raising=False)
    with TestClient(create_app()) as client:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert client.get("/readyz").status_code == 503


def test_readiness_with_database(db_engine: Engine) -> None:
    with TestClient(create_app(db_engine)) as client:
        response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_failure_hides_database_error() -> None:
    engine = Mock(spec=Engine)
    engine.connect.side_effect = OperationalError(
        None, None, Exception("private-error-placeholder")
    )
    with TestClient(create_app(engine)) as client:
        response = client.get("/readyz")
        assert client.get("/healthz").status_code == 200
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
    engine.dispose.assert_not_called()


def test_readiness_uses_environment_and_disposes_owned_engine(
    monkeypatch: pytest.MonkeyPatch, db_engine: Engine
) -> None:
    create_engine = Mock(return_value=db_engine)
    monkeypatch.setenv("CLOUDSCOPE_DATABASE_URL", "postgresql+psycopg://localhost/test")
    monkeypatch.setattr("cloudscope.api.app.create_db_engine", create_engine)
    with patch.object(db_engine, "dispose", wraps=db_engine.dispose) as dispose:
        with TestClient(create_app()) as client:
            assert client.get("/readyz").status_code == 200
        dispose.assert_called_once_with()
    create_engine.assert_called_once_with("postgresql+psycopg://localhost/test")


@pytest.mark.parametrize(
    "url",
    ["invalid-url-placeholder", "sqlite:///test.db", "postgresql+psycopg://localhost:bad/db"],
)
def test_invalid_database_configuration_does_not_break_liveness(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.setenv("CLOUDSCOPE_DATABASE_URL", url)
    with TestClient(create_app()) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/readyz").status_code == 503
