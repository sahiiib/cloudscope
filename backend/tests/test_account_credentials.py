"""Credential isolation, write-only web flows and retained account identity."""

import logging
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from moto import mock_aws
from pydantic import SecretStr
from sqlalchemy.orm import Session
from test_auth import CSRF
from test_auth import client as client
from test_auth import user as user
from test_users_api import admin as admin

from cloudscope.collector.access import AccountAccess
from cloudscope.collector.alibaba import AlibabaClientFactory
from cloudscope.collector.aws import AWSClientFactory
from cloudscope.config import AccountConfig
from cloudscope.credentials import (
    CredentialError,
    Credentials,
    KubernetesCredentialStore,
    LocalCredentialStore,
    credential_store,
)
from cloudscope.db.models import Account

BODY = {"provider": "aws", "account_id": "111111111111", "name": "Demo", "regions": "all"}
URL = "/api/accounts/aws/111111111111"
KEYS = {"access_key_id": "fixture-key", "secret_access_key": "fixture-secret"}


class AccessProvider:
    def test_access(self, account: AccountConfig) -> list[str]:
        return ["us-east-1"]


def configure(admin: TestClient, tmp_path: Path) -> LocalCredentialStore:
    tmp_path.chmod(0o700)
    store = LocalCredentialStore(tmp_path)
    admin.app.state.dedicated_credentials_enabled = True
    admin.app.state.credential_store = store
    admin.app.state.account_access = AccountAccess(
        {"aws": AccessProvider(), "alibaba": AccessProvider()}
    )
    return store


def test_bound_immutable_local_versions_and_redacted_repr(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    store = LocalCredentialStore(tmp_path)
    keys = Credentials.model_validate(KEYS)
    first = store.create("aws", BODY["account_id"], keys)
    second = store.create("aws", BODY["account_id"], keys)
    assert first != second
    assert store.read(first, "aws", BODY["account_id"]).secret_access_key == SecretStr(
        "fixture-secret"
    )
    assert "fixture-secret" not in repr(keys)
    for reference, provider, account in [
        (first, "alibaba", BODY["account_id"]),
        (first, "aws", "222222222222"),
        ("../other", "aws", BODY["account_id"]),
    ]:
        with pytest.raises(CredentialError):
            store.read(reference, provider, account)


def test_kubernetes_binding_and_requests_are_scoped(monkeypatch: pytest.MonkeyPatch) -> None:
    store = KubernetesCredentialStore()
    docs: dict[str, Any] = {}
    requests: list[tuple[str, str]] = []

    def request(
        method: str, suffix: str = "", body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        requests.append((method, suffix))
        if body:
            docs[body["metadata"]["name"]] = body
            return body
        return docs[suffix[1:]]

    monkeypatch.setattr(store, "_request", request)
    ref = store.create("aws", BODY["account_id"], Credentials.model_validate(KEYS))
    assert (
        store.read(ref, "aws", BODY["account_id"]).access_key_id.get_secret_value() == "fixture-key"
    )
    assert requests == [("POST", ""), ("GET", "/" + ref)]
    docs[ref]["metadata"]["labels"]["cloudscope.io/owner"] = "different-release"
    with pytest.raises(CredentialError):
        store.read(ref, "aws", BODY["account_id"])


def test_disabled_and_cluster_cannot_use_local_adapter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CLOUDSCOPE_DEDICATED_CREDENTIALS_ENABLED", "false")
    with pytest.raises(CredentialError, match="Disabled"):
        credential_store()
    monkeypatch.setenv("CLOUDSCOPE_DEDICATED_CREDENTIALS_ENABLED", "true")
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "kubernetes.default.svc")
    monkeypatch.setenv("CLOUDSCOPE_LOCAL_CREDENTIALS_DIRECTORY", str(tmp_path))
    with pytest.raises(CredentialError, match="ForbiddenInCluster"):
        credential_store()


def test_web_keys_never_echo_and_rotation_is_optimistic(
    admin: TestClient, db_session: Session, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store = configure(admin, tmp_path)
    with caplog.at_level(logging.INFO):
        result = admin.post(
            "/api/accounts",
            json={**BODY, "connection_mode": "dedicated", "credentials": KEYS},
            headers=CSRF,
        )
    assert result.status_code == 201
    assert result.json()["credentials_configured"] and result.json()["configuration_version"] == 1
    assert "credential_reference" not in result.json()
    row = db_session.get_one(Account, ("aws", BODY["account_id"]))
    ref = row.credential_reference
    assert ref and store.read(ref, "aws", BODY["account_id"])
    for output in [result.text, admin.get("/api/accounts").text, caplog.text]:
        assert all(value not in output for value in KEYS.values())
    updated = admin.patch(URL, json={"credentials": KEYS, "expected_version": 1}, headers=CSRF)
    assert updated.status_code == 200 and updated.json()["configuration_version"] == 2
    db_session.expire_all()
    current = db_session.get_one(Account, ("aws", BODY["account_id"]))
    assert current.credential_reference != ref
    assert (
        admin.patch(
            URL, json={"credentials": KEYS, "expected_version": 1}, headers=CSRF
        ).status_code
        == 409
    )
    assert len(list(tmp_path.iterdir())) == 2
    assert (
        admin.patch(
            URL, json={"connection_mode": "runtime", "expected_version": 2}, headers=CSRF
        ).status_code
        == 200
    )


def test_failed_validation_preserves_prior_connection(
    admin: TestClient, db_session: Session, tmp_path: Path
) -> None:
    configure(admin, tmp_path)
    assert (
        admin.post(
            "/api/accounts",
            json={**BODY, "connection_mode": "dedicated", "credentials": KEYS},
            headers=CSRF,
        ).status_code
        == 201
    )
    old = db_session.get_one(Account, ("aws", BODY["account_id"])).credential_reference

    class Denied(AccessProvider):
        def test_access(self, account: AccountConfig) -> list[str]:
            raise CredentialError("AccountIdentityMismatch")

    admin.app.state.account_access = AccountAccess({"aws": Denied()})
    result = admin.patch(URL, json={"credentials": KEYS, "expected_version": 1}, headers=CSRF)
    assert result.status_code == 422 and "AccountIdentityMismatch" in result.text
    db_session.expire_all()
    row = db_session.get_one(Account, ("aws", BODY["account_id"]))
    assert row.credential_reference == old and row.configuration_version == 1


def test_explicit_adoption_preserves_row_and_ui_wins_file_sync(
    admin: TestClient, db_session: Session
) -> None:
    from dataclasses import asdict
    from datetime import UTC, datetime

    from sqlalchemy.orm import sessionmaker
    from test_load_balancers import normalized
    from test_runner import FakeProvider

    from cloudscope.collector.runner import SyncRunner
    from cloudscope.db.models import Instance, LoadBalancer, SyncRun

    db_session.add(Account(**BODY, source="file", cloud_alias="existing-alias", enabled=False))
    db_session.flush()
    config = AccountConfig(**BODY)
    now = datetime.now(UTC)
    db_session.add(
        Instance(
            **asdict(FakeProvider().scan(config, "us-east-1")[0]), first_seen=now, last_observed=now
        )
    )
    db_session.add(LoadBalancer(**asdict(normalized()), first_seen=now, last_observed=now))
    run = SyncRun(trigger="manual")
    db_session.add(run)
    db_session.commit()
    assert (
        admin.post(
            URL + "/adopt", json={"confirmed": False, "expected_version": 1}, headers=CSRF
        ).status_code
        == 422
    )
    adopted = admin.post(
        URL + "/adopt", json={"confirmed": True, "expected_version": 1}, headers=CSRF
    )
    assert adopted.status_code == 200 and adopted.json()["source"] == "ui"
    assert adopted.json()["instance_count"] == 1
    assert adopted.json()["cloud_alias"] == "existing-alias" and not adopted.json()["enabled"]
    sessions = sessionmaker(
        bind=db_session.connection(),
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    SyncRunner(sessions, {}).run([AccountConfig(**{**BODY, "name": "old file name"})])
    db_session.expire_all()
    row = db_session.get_one(Account, ("aws", BODY["account_id"]))
    assert row.source == "ui" and row.name == "Demo" and not row.enabled
    from sqlalchemy import select

    assert db_session.scalar(select(Instance)).present
    assert db_session.scalar(select(LoadBalancer)).present
    assert db_session.get(SyncRun, run.id) is not None


def test_secret_inputs_rejected_without_echo_and_feature_off(admin: TestClient) -> None:
    assert (
        admin.post(
            "/api/accounts",
            json={**BODY, "connection_mode": "dedicated", "credentials": KEYS},
            headers=CSRF,
        ).status_code
        == 409
    )
    result = admin.post(
        "/api/accounts",
        json={**BODY, "credentials": {**KEYS, "extra": "private-placeholder"}},
        headers=CSRF,
    )
    assert result.status_code == 422 and "private-placeholder" not in result.text
    assert admin.get("/api/accounts/capabilities").json() == {"dedicated_credentials": False}


def test_aws_identity_checked_before_inventory_no_base_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MOTO_ACCOUNT_ID", BODY["account_id"])
    with mock_aws():
        account = AccountConfig(
            **BODY, connection_mode="dedicated", credential_reference="cs-" + "a" * 32
        )
        factory = AWSClientFactory(credential_loader=lambda _: Credentials.model_validate(KEYS))
        reader = factory(account, "us-east-1")
        assert reader.call("describe_regions")["Regions"]
        with pytest.raises(CredentialError, match="IdentityMismatch"):
            factory(account.model_copy(update={"account_id": "222222222222"}), "us-east-1")
        broken = AWSClientFactory(
            credential_loader=lambda _: (_ for _ in ()).throw(CredentialError("MissingSecret"))
        )
        with pytest.raises(CredentialError, match="MissingSecret"):
            broken(account, "us-east-1")


def test_alibaba_identity_and_selected_keys_are_used(monkeypatch: pytest.MonkeyPatch) -> None:
    account = AccountConfig(
        provider="alibaba",
        account_id="1111111111111111",
        name="Demo",
        regions="all",
        connection_mode="dedicated",
        credential_reference="cs-" + "b" * 32,
    )
    seen: list[tuple[str, str]] = []

    class STS:
        def get_caller_identity_with_options(self, options: Any) -> Any:
            class Body:
                def to_map(self) -> dict[str, str]:
                    return {"AccountId": account.account_id}

            class Response:
                body = Body()

            return Response()

    def builder(service: str, config: Any) -> Any:
        seen.append((service, config.access_key_id))
        return STS() if service == "sts" else object()

    monkeypatch.delenv("ALIBABA_CLOUD_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", raising=False)
    AlibabaClientFactory(
        builder=builder, credential_loader=lambda _: Credentials.model_validate(KEYS)
    )(account, "cn-hangzhou")
    assert seen == [("sts", "fixture-key"), ("ecs", "fixture-key"), ("vpc", "fixture-key")]


@pytest.mark.parametrize("status", [302, 403, 404, 500])
def test_kubernetes_https_errors_are_sanitized(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    from cloudscope import credentials as module

    calls: list[tuple[str, str]] = []
    ca_context = object()
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "kubernetes.default.svc")
    monkeypatch.setattr(Path, "read_text", lambda *args, **kwargs: "projected-token")

    def context(*, cafile: str) -> object:
        assert cafile.replace("\\", "/") == "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
        return ca_context

    class Connection:
        def __init__(self, host: str, port: int, **options: Any):
            assert host == "kubernetes.default.svc" and port == 443
            assert options["context"] is ca_context and options["timeout"] == 10

        def request(self, method: str, path: str, **options: Any) -> None:
            calls.append((method, path))
            assert options["headers"]["Authorization"] == "Bearer projected-token"

        def getresponse(self) -> Any:
            class Response:
                pass

            response = Response()
            response.status = status
            return response

        def close(self) -> None:
            pass

    monkeypatch.setattr(module.ssl, "create_default_context", context)
    monkeypatch.setattr(module.http.client, "HTTPSConnection", Connection)
    with pytest.raises(CredentialError, match="CredentialStoreUnavailable"):
        KubernetesCredentialStore().create(
            "aws", BODY["account_id"], Credentials.model_validate(KEYS)
        )
    assert calls == [("POST", "/api/v1/namespaces/cloudscope-credentials/secrets")]


def test_adoption_requires_admin_full_session(client: TestClient) -> None:
    from test_auth import login

    data = {"confirmed": True, "expected_version": 1}
    assert client.post(URL + "/adopt", json=data, headers=CSRF).status_code == 401
    login(client)
    assert client.get("/api/accounts/capabilities").status_code == 403
    assert client.post(URL + "/adopt", json=data, headers=CSRF).status_code == 403


def test_migration_preserves_old_rows_and_blocks_unsafe_downgrade(db_engine: Any) -> None:
    from uuid import uuid4

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect, text

    name = "cloudscope_credential_migration_" + uuid4().hex
    admin_engine = create_engine(
        db_engine.url.set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    engine = create_engine(db_engine.url.set(database=name))
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    with admin_engine.connect() as admin_connection:
        admin_connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "0006")
            connection.execute(
                text(
                    "INSERT INTO accounts(provider, account_id, name, source, enabled) "
                    "VALUES('aws', '111111111111', 'Retained', 'file', false)"
                )
            )
            before = connection.execute(
                text("SELECT provider, account_id, name, source, enabled, created_at FROM accounts")
            ).all()
            command.upgrade(config, "head")
            assert (
                connection.execute(
                    text(
                        "SELECT provider, account_id, name, source, enabled, created_at "
                        "FROM accounts"
                    )
                ).all()
                == before
            )
            assert connection.execute(
                text(
                    "SELECT connection_mode, credential_reference, configuration_version "
                    "FROM accounts"
                )
            ).one() == ("runtime", None, 1)
            names = {item["name"] for item in inspect(connection).get_check_constraints("accounts")}
            assert "ck_accounts_connection" in names
            connection.execute(
                text(
                    "UPDATE accounts SET source='ui', connection_mode='dedicated', "
                    "credential_reference='cs-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'"
                )
            )
            with pytest.raises(RuntimeError, match="before downgrade"):
                command.downgrade(config, "0007")
    finally:
        engine.dispose()
        with admin_engine.connect() as admin_connection:
            admin_connection.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
        admin_engine.dispose()
