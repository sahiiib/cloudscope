import pytest
from fastapi.testclient import TestClient

from cloudscope.api.app import create_app


@pytest.mark.parametrize("path", ["/healthz", "/readyz"])
def test_health_endpoints(path: str) -> None:
    with TestClient(create_app()) as client:
        response = client.get(path)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
