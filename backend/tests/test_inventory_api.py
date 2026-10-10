"""Inventory endpoints exercise PostgreSQL search, JSONB and access control."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_auth import CSRF, login
from test_auth import client as client
from test_auth import user as user

from cloudscope.db.models import Account, Instance, SyncResult, SyncRun, User


@pytest.fixture
def inventory(db_session: Session) -> None:
    db_session.add_all(
        [
            Account(provider="aws", account_id="111111111111", name="Alpha"),
            Account(provider="alibaba", account_id="222222222222", name="Beta"),
        ]
    )
    db_session.flush()
    for i, (provider, account, region, name, state, present) in enumerate(
        [
            ("aws", "111111111111", "eu-central-1", "Web_100%", "running", True),
            ("aws", "111111111111", "us-east-1", "Database", "stopped", True),
            ("alibaba", "222222222222", "eu-central-1", "Cache", "running", True),
            ("aws", "111111111111", "eu-central-1", "Gone", "terminated", False),
        ]
    ):
        db_session.add(
            Instance(
                provider=provider,
                account_id=account,
                region=region,
                instance_id=f"i-test-{i}",
                name=name,
                state=state,
                provider_state=state,
                instance_type="test.small",
                present=present,
                private_ips=[f"10.0.0.{i + 1}"],
                public_ips=[],
                tags={"env": "Production" if i == 0 else "test", "team": "infra"},
                details={"cpu": 2},
                raw={"test": True},
            )
        )
    db_session.commit()


@pytest.mark.parametrize(
    "query,expected",
    [
        ("WEB", 1),
        ("i-test-1", 1),
        ("10.0.0.3", 1),
        ("production", 1),
        ("TEAM", 3),
        ("%", 1),
        ("_", 1),
        ("no-match", 0),
    ],
)
def test_search(client: TestClient, inventory: None, query: str, expected: int) -> None:
    login(client)
    response = client.get("/api/instances", params={"q": query})
    assert response.status_code == 200
    assert response.json()["total"] == expected


@pytest.mark.parametrize(
    "params,expected",
    [
        ({"provider": "aws"}, 2),
        ({"provider": ["aws", "alibaba"]}, 3),
        ({"account_id": "222222222222"}, 1),
        ({"region": "us-east-1"}, 1),
        ({"state": "running"}, 2),
        ({"tag": "env=Production"}, 1),
        ({"tag": "team"}, 3),
        ({"tag": ["env=test", "team=infra"]}, 2),
        ({"include_missing": True}, 4),
        ({"provider": "aws", "state": "running", "region": "us-east-1"}, 0),
    ],
)
def test_filters(client: TestClient, inventory: None, params: dict, expected: int) -> None:
    login(client)
    assert client.get("/api/instances", params=params).json()["total"] == expected


def test_pagination_detail_facets_accounts(client: TestClient, inventory: None) -> None:
    login(client)
    response = client.get(
        "/api/instances", params={"sort": "-name", "page_size": 1, "page": 2}
    ).json()
    assert response["total"] == 3 and response["items"][0]["name"] == "Database"
    assert "raw" not in response["items"][0]
    assert client.get("/api/instances?page=10").json()["items"] == []
    for sort in ["launch_time", "-last_observed", "region", "account"]:
        assert client.get("/api/instances", params={"sort": sort}).status_code == 200
    facets = client.get("/api/instances/facets?provider=aws&region=eu-central-1").json()
    assert facets["providers"] == [{"value": "alibaba", "count": 1}, {"value": "aws", "count": 1}]
    assert facets["regions"] == [
        {"value": "eu-central-1", "count": 1},
        {"value": "us-east-1", "count": 1},
    ]
    detail = client.get("/api/instances/aws/111111111111/eu-central-1/i-test-0").json()
    assert detail["details"] == {"cpu": 2} and detail["raw"] == {"test": True}
    assert client.get("/api/instances/aws/111111111111/eu-central-1/missing").status_code == 404
    assert [a["instance_count"] for a in client.get("/api/accounts").json()] == [1, 2]


@pytest.mark.parametrize(
    "query", ["page=0", "page_size=501", "sort=raw", "provider=bad", "state=bad"]
)
def test_invalid_filters(client: TestClient, query: str) -> None:
    login(client)
    assert client.get(f"/api/instances?{query}").status_code == 422


def test_auth_and_sync_history(
    client: TestClient, db_session: Session, inventory: None, user: User
) -> None:
    for path in ["/api/instances", "/api/instances/facets", "/api/accounts", "/api/sync/runs"]:
        assert client.get(path).status_code == 401
    login(client)
    assert client.post("/api/sync/runs", headers=CSRF).status_code == 403
    user.is_admin = True
    run = SyncRun(trigger="manual", status="success", instances_seen=3)
    db_session.add(run)
    db_session.flush()
    db_session.add(
        SyncResult(
            run_id=run.id,
            provider="aws",
            account_id="111111111111",
            region="eu-central-1",
            status="success",
            instances_seen=3,
            duration_ms=10,
        )
    )
    db_session.commit()
    assert client.get("/api/sync/runs?limit=1").json()[0]["id"] == run.id
    assert client.get(f"/api/sync/runs/{run.id}").json()["results"][0]["instances_seen"] == 3
    assert client.get("/api/sync/runs/9999999").status_code == 404
    assert client.post("/api/sync/runs").status_code == 403


def test_manual_sync_response(client: TestClient, db_session: Session, user: User) -> None:
    from fastapi import HTTPException

    class Service:
        running = False

        def start(self) -> None:
            if self.running:
                raise HTTPException(409, "Another collection is running")
            self.running = True

    user.is_admin = True
    db_session.commit()
    client.app.state.manual_sync = Service()
    try:
        login(client)
        assert client.post("/api/sync/runs", headers=CSRF).status_code == 202
        assert client.post("/api/sync/runs", headers=CSRF).status_code == 409
    finally:
        client.app.state.manual_sync = None
