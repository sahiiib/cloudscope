"""Bound, immutable credential versions; no credential material belongs in the DB."""

import base64
import hashlib
import http.client
import json
import os
import re
import ssl
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from cloudscope.config import AccountConfig


class CredentialError(Exception):
    """Safe diagnostic; do not attach SDK/HTTP response text."""


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    access_key_id: SecretStr = Field(min_length=1, max_length=256)
    secret_access_key: SecretStr = Field(min_length=1, max_length=4096)
    session_token: SecretStr | None = Field(default=None, max_length=8192)


class CredentialStore(Protocol):
    def create(self, provider: str, account_id: str, keys: Credentials) -> str: ...
    def read(self, reference: str, provider: str, account_id: str) -> Credentials: ...


def labels(owner: str, provider: str, account_id: str) -> dict[str, str]:
    return {
        "cloudscope.io/owner": owner,
        "cloudscope.io/provider": provider,
        "cloudscope.io/account": hashlib.sha256(account_id.encode()).hexdigest()[:32],
    }


def reference_name(value: str) -> str:
    if not re.fullmatch(r"cs-[0-9a-f]{32}", value):
        raise CredentialError("InvalidCredentialReference")
    return value


def document(owner: str, provider: str, account_id: str, keys: Credentials) -> dict[str, Any]:
    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "type": "Opaque",
        "immutable": True,
        "metadata": {"name": "cs-" + uuid4().hex, "labels": labels(owner, provider, account_id)},
        "data": {
            key: base64.b64encode(value.get_secret_value().encode()).decode()
            for key in Credentials.model_fields
            if (value := getattr(keys, key)) is not None
        },
    }


def decode(value: dict[str, Any], owner: str, provider: str, account_id: str) -> Credentials:
    try:
        if (
            value.get("immutable") is not True
            or value.get("type") != "Opaque"
            or value["metadata"]["labels"] != labels(owner, provider, account_id)
        ):
            raise ValueError
        return Credentials.model_validate(
            {
                key: base64.b64decode(data, validate=True).decode()
                for key, data in value["data"].items()
            }
        )
    except Exception:
        raise CredentialError("InvalidCredentialBinding") from None


class KubernetesCredentialStore:
    def __init__(self, namespace: str = "cloudscope-credentials", owner: str = "cloudscope"):
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", namespace) or not re.fullmatch(
            r"[a-z0-9][a-z0-9-]{0,62}", owner
        ):
            raise CredentialError("InvalidCredentialStoreConfiguration")
        self.namespace, self.owner = namespace, owner

    def _request(
        self, method: str, suffix: str = "", body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            base = Path("/var/run/secrets/kubernetes.io/serviceaccount")
            token = (base / "token").read_text().strip()  # Re-read projected, rotating token.
            connection = http.client.HTTPSConnection(
                os.environ["KUBERNETES_SERVICE_HOST"],
                int(os.environ.get("KUBERNETES_SERVICE_PORT_HTTPS", "443")),
                timeout=10,
                context=ssl.create_default_context(cafile=str(base / "ca.crt")),
            )
            try:
                connection.request(
                    method,
                    f"/api/v1/namespaces/{self.namespace}/secrets{suffix}",
                    body=json.dumps(body) if body else None,
                    headers={
                        "Authorization": "Bearer " + token,
                        "Content-Type": "application/json",
                    },
                )
                response = connection.getresponse()
                if response.status not in (200, 201):
                    raise CredentialError("CredentialStoreUnavailable")
                raw = response.read(65537)
                if len(raw) > 65536:
                    raise CredentialError("InvalidCredentialResponse")
                result: dict[str, Any] = json.loads(raw)
                return result
            finally:
                connection.close()
        except CredentialError:
            raise
        except Exception:
            raise CredentialError("CredentialStoreUnavailable") from None

    def create(self, provider: str, account_id: str, keys: Credentials) -> str:
        value = document(self.owner, provider, account_id, keys)
        self._request("POST", body=value)
        return str(value["metadata"]["name"])

    def read(self, reference: str, provider: str, account_id: str) -> Credentials:
        value = self._request("GET", "/" + reference_name(reference))
        if value.get("metadata", {}).get("name") != reference:
            raise CredentialError("InvalidCredentialReference")
        return decode(value, self.owner, provider, account_id)


class LocalCredentialStore:
    """Explicit development-only adapter; directory must be private to the operator."""

    def __init__(self, path: Path, owner: str = "cloudscope"):
        self.path, self.owner = path, owner
        if not path.is_dir():
            raise CredentialError("PrivateCredentialDirectoryRequired")
        if os.name != "nt" and path.stat().st_mode & 0o077:
            raise CredentialError("PrivateCredentialDirectoryRequired")

    def create(self, provider: str, account_id: str, keys: Credentials) -> str:
        value = document(self.owner, provider, account_id, keys)
        name = str(value["metadata"]["name"])
        descriptor = os.open(self.path / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump(value, stream)
        return name

    def read(self, reference: str, provider: str, account_id: str) -> Credentials:
        try:
            path = self.path / reference_name(reference)
            if path.is_symlink() or path.stat().st_size > 65536:
                raise CredentialError("InvalidCredentialReference")
            value = json.loads(path.read_text())
        except CredentialError:
            raise
        except Exception:
            raise CredentialError("CredentialStoreUnavailable") from None
        return decode(value, self.owner, provider, account_id)


def credential_store() -> CredentialStore:
    if os.environ.get("CLOUDSCOPE_DEDICATED_CREDENTIALS_ENABLED", "false").lower() != "true":
        raise CredentialError("DedicatedCredentialsDisabled")
    owner = os.environ.get("CLOUDSCOPE_CREDENTIALS_OWNER", "cloudscope")
    local = os.environ.get("CLOUDSCOPE_LOCAL_CREDENTIALS_DIRECTORY")
    if local:
        if os.environ.get("KUBERNETES_SERVICE_HOST"):
            raise CredentialError("LocalCredentialStoreForbiddenInCluster")
        return LocalCredentialStore(Path(local), owner)
    return KubernetesCredentialStore(
        os.environ.get("CLOUDSCOPE_CREDENTIALS_NAMESPACE", "cloudscope-credentials"), owner
    )


def account_credentials(account: AccountConfig) -> Credentials:
    if account.connection_mode != "dedicated" or not account.credential_reference:
        raise CredentialError("DedicatedCredentialsMissing")
    return credential_store().read(
        account.credential_reference, account.provider, account.account_id
    )
