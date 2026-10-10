"""Render deployment variants; no Kubernetes cluster or cloud access needed."""

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

CHART = Path(__file__).resolve().parents[2] / "deploy/helm/cloudscope"
pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="Helm is not installed")


def render(*settings: str) -> list[dict[str, Any]]:
    args = ["helm", "template", "cloudscope", str(CHART)]
    for setting in settings:
        args.extend(["--set", setting])
    result = subprocess.run(args, check=True, capture_output=True, text=True)
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def resource(docs: list[dict[str, Any]], kind: str, name: str) -> dict[str, Any]:
    return next(doc for doc in docs if doc["kind"] == kind and doc["metadata"]["name"] == name)


def test_default_chart_wiring_and_security() -> None:
    docs = render("api.forwardedAllowIPs=10.0.0.0/16")
    assert not any(doc["kind"] == "Secret" for doc in docs)
    api = resource(docs, "Deployment", "cloudscope-api")["spec"]
    assert api["replicas"] == 2
    container = api["template"]["spec"]["containers"][0]
    env = {item["name"]: item for item in container["env"]}
    assert env["CLOUDSCOPE_FORWARDED_ALLOW_IPS"]["value"] == "10.0.0.0/16"
    assert env["CLOUDSCOPE_DATABASE_URL"]["valueFrom"]["secretKeyRef"]["key"] == "DATABASE_URL"
    assert container["readinessProbe"]["httpGet"]["path"] == "/readyz"
    assert container["livenessProbe"]["httpGet"]["path"] == "/healthz"
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    web = resource(docs, "Deployment", "cloudscope-web")["spec"]["template"]["spec"]
    assert {m["mountPath"] for m in web["containers"][0]["volumeMounts"]} == {
        "/etc/nginx/conf.d",
        "/tmp",
    }
    cron = resource(docs, "CronJob", "cloudscope-collector")["spec"]
    assert cron["schedule"] == "*/15 * * * *"
    assert cron["concurrencyPolicy"] == "Forbid"
    assert cron["jobTemplate"]["spec"]["backoffLimit"] == 1
    assert cron["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]["args"] == [
        "collect",
        "--trigger",
        "schedule",
    ]
    postgres = resource(docs, "StatefulSet", "cloudscope-postgres")["spec"]
    assert postgres["volumeClaimTemplates"][0]["spec"]["resources"]["requests"]["storage"] == "10Gi"
    migrate = resource(docs, "Job", "cloudscope-migrate")
    assert migrate["metadata"]["annotations"]["helm.sh/hook"] == "post-install,post-upgrade"
    assert migrate["spec"]["template"]["spec"]["containers"][0]["args"] == ["upgrade", "head"]
    assert migrate["spec"]["template"]["spec"]["initContainers"][0]["name"] == "wait-for-database"
    policy = resource(docs, "NetworkPolicy", "cloudscope-postgres")["spec"]
    selector = policy["ingress"][0]["from"][0]["podSelector"]
    assert selector["matchExpressions"][0]["values"] == ["api", "collector", "migrate"]


def test_external_database_ingress_accounts_and_irsa() -> None:
    docs = render(
        "postgres.enabled=false",
        "existingSecret=external",
        "ingress.enabled=true",
        "ingress.tls[0].secretName=tls",
        "ingress.tls[0].hosts[0]=cloudscope.local",
        "serviceAccount.annotations.eks\\.amazonaws\\.com/role-arn=placeholder-role",
        "accounts[0].provider=aws",
        "accounts[0].account_id=111111111111",
        "accounts[0].name=example",
        "accounts[0].regions[0]=eu-central-1",
    )
    assert not any(doc["kind"] == "StatefulSet" for doc in docs)
    migrate = resource(docs, "Job", "cloudscope-migrate")
    assert migrate["metadata"]["annotations"]["helm.sh/hook"] == "pre-install,pre-upgrade"
    env = migrate["spec"]["template"]["spec"]["containers"][0]["env"][0]
    assert env["valueFrom"]["secretKeyRef"]["name"] == "external"
    ingress = resource(docs, "Ingress", "cloudscope")["spec"]
    assert ingress["tls"][0]["secretName"] == "tls"
    assert ingress["rules"][0]["http"]["paths"][0]["backend"]["service"]["name"] == "cloudscope-web"
    sa = resource(docs, "ServiceAccount", "cloudscope")
    assert sa["metadata"]["annotations"]["eks.amazonaws.com/role-arn"] == "placeholder-role"
    config = resource(docs, "ConfigMap", "cloudscope-accounts")
    assert yaml.safe_load(config["data"]["accounts.yaml"])["accounts"][0]["provider"] == "aws"


def test_chart_created_secret_and_required_values() -> None:
    docs = render(
        "secrets.create=true",
        "secrets.data.DATABASE_URL=placeholder",
        "secrets.data.SECRET_KEY=placeholder",
        "secrets.data.POSTGRES_PASSWORD=placeholder",
    )
    assert (
        resource(docs, "Secret", "cloudscope")["stringData"]["POSTGRES_PASSWORD"] == "placeholder"
    )
    with pytest.raises(subprocess.CalledProcessError):
        render("secrets.create=true")
    with pytest.raises(subprocess.CalledProcessError):
        render("api.forwardedAllowIPs=*")
