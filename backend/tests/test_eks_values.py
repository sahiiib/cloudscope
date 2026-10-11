"""Offline contract checks for the EKS overlay and external secret wiring."""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from cloudscope.config import AccountsConfig

ROOT = Path(__file__).resolve().parents[2]
VALUES = ROOT / "deploy/helm/values.eks.yaml"
MANIFEST = ROOT / "deploy/eks/external-secret.yaml"


def resource(docs: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    return next(doc for doc in docs if doc["kind"] == kind)


def test_external_secret_uses_operator_identity_and_explicit_runtime_keys() -> None:
    docs = list(yaml.safe_load_all(MANIFEST.read_text()))
    values = yaml.safe_load(VALUES.read_text())
    store = resource(docs, "SecretStore")
    secret = resource(docs, "ExternalSecret")
    assert store["apiVersion"] == secret["apiVersion"] == "external-secrets.io/v1"
    assert store["metadata"]["namespace"] == secret["metadata"]["namespace"] == "cloudscope"
    provider = store["spec"]["provider"]["aws"]
    assert provider == {"service": "SecretsManager", "region": "eu-central-1"}
    # No static credentials, serviceAccountRef, or extra AssumeRole hop for ESO.
    spec = secret["spec"]
    assert spec["secretStoreRef"] == {"name": store["metadata"]["name"], "kind": "SecretStore"}
    assert spec["target"]["name"] == values["existingSecret"]
    assert values["secrets"]["create"] is False
    assert spec["target"]["creationPolicy"] == "Owner"
    assert spec["target"]["deletionPolicy"] == "Retain"
    expected = {
        "DATABASE_URL",
        "SECRET_KEY",
        "ALIBABA_CLOUD_ACCESS_KEY_ID",
        "ALIBABA_CLOUD_ACCESS_KEY_SECRET",
    }
    assert {entry["secretKey"] for entry in spec["data"]} == expected
    assert "dataFrom" not in spec
    for entry in spec["data"]:
        assert entry["remoteRef"] == {"key": "cloudscope/prod", "property": entry["secretKey"]}


def test_eks_accounts_and_secret_reader_permissions_are_scoped() -> None:
    values = yaml.safe_load(VALUES.read_text())
    accounts = AccountsConfig.model_validate({"accounts": values["accounts"]}).accounts
    assert {account.provider for account in accounts} == {"aws", "alibaba"}
    assert all(account.role_arn and account.regions == "all" for account in accounts)
    assert (
        next(account for account in accounts if account.provider == "aws").external_id
        == "cloudscope"
    )
    assert values["serviceAccount"] == {"name": "cloudscope", "annotations": {}}
    assert values["image"]["backend"]["tag"] == values["image"]["web"]["tag"] == ""
    statements = json.loads((ROOT / "deploy/eks/eso-read-policy.json").read_text())["Statement"]
    assert len(statements) == 1
    assert set(statements[0]["Action"]) == {
        "secretsmanager:GetSecretValue",
        "secretsmanager:DescribeSecret",
    }
    assert statements[0]["Resource"] == (
        "arn:aws:secretsmanager:eu-central-1:111111111111:secret:cloudscope/prod-??????"
    )


@pytest.mark.skipif(shutil.which("helm") is None, reason="Helm is not installed")
@pytest.mark.parametrize("internal_database", [False, True])
def test_eks_chart_database_modes_and_alb(internal_database: bool) -> None:
    result = subprocess.run(
        [
            "helm",
            "template",
            "cloudscope",
            str(ROOT / "deploy/helm/cloudscope"),
            "--namespace",
            "cloudscope",
            "-f",
            str(VALUES),
            "--set",
            "image.backend.tag=sha-test,image.web.tag=sha-test",
            "--set",
            f"postgres.enabled={str(internal_database).lower()}",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    docs = [doc for doc in yaml.safe_load_all(result.stdout) if doc]
    assert not any(doc["kind"] == "Secret" for doc in docs)
    assert any(doc["kind"] == "StatefulSet" for doc in docs) is internal_database
    hook = resource(docs, "Job")["metadata"]["annotations"]["helm.sh/hook"]
    assert hook == ("post-install,pre-upgrade" if internal_database else "pre-install,pre-upgrade")
    assert resource(docs, "ServiceAccount")["metadata"]["name"] == "cloudscope"
    ingress = resource(docs, "Ingress")
    assert ingress["spec"]["ingressClassName"] == "alb"
    assert "tls" not in ingress["spec"]
    annotations = ingress["metadata"]["annotations"]
    assert annotations["alb.ingress.kubernetes.io/scheme"] == "internal"
    assert annotations["alb.ingress.kubernetes.io/target-type"] == "ip"
    assert json.loads(annotations["alb.ingress.kubernetes.io/listen-ports"]) == [
        {"HTTP": 80},
        {"HTTPS": 443},
    ]
    assert annotations["alb.ingress.kubernetes.io/ssl-redirect"] == "443"
    assert annotations["alb.ingress.kubernetes.io/certificate-arn"].startswith("arn:aws:acm:")
    backend = ingress["spec"]["rules"][0]["http"]["paths"][0]["backend"]["service"]
    assert backend == {"name": "cloudscope-web", "port": {"number": 8080}}
    api = next(
        doc
        for doc in docs
        if doc["kind"] == "Deployment" and doc["metadata"]["name"].endswith("-api")
    )
    pod = api["spec"]["template"]["spec"]
    assert pod["serviceAccountName"] == "cloudscope"
    env = {entry["name"]: entry for entry in pod["containers"][0]["env"]}
    assert env["CLOUDSCOPE_COOKIE_SECURE"]["value"] == "true"
    assert env["CLOUDSCOPE_FORWARDED_ALLOW_IPS"]["value"] == "10.0.0.0/16"
    assert env["CLOUDSCOPE_DATABASE_URL"]["valueFrom"]["secretKeyRef"] == {
        "name": "cloudscope",
        "key": "DATABASE_URL",
    }
