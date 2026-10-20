"""Render deployment variants; no Kubernetes cluster or cloud access needed."""

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

CHART = Path(__file__).resolve().parents[2] / "deploy/helm/cloudscope"
pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="Helm is not installed")


def render(
    *settings: str, release: str = "cloudscope", namespace: str = "default"
) -> list[dict[str, Any]]:
    args = [
        "helm",
        "template",
        release,
        str(CHART),
        "--namespace",
        namespace,
        "--set",
        "image.backend.tag=sha-test,image.web.tag=sha-test",
    ]
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
    assert migrate["metadata"]["annotations"]["helm.sh/hook"] == "post-install,pre-upgrade"
    assert migrate["spec"]["template"]["spec"]["containers"][0]["args"] == ["upgrade", "head"]
    assert migrate["spec"]["template"]["spec"]["initContainers"][0]["name"] == "wait-for-database"
    policy = resource(docs, "NetworkPolicy", "cloudscope-postgres")["spec"]
    selector = policy["ingress"][0]["from"][0]["podSelector"]
    assert selector["matchExpressions"][0]["values"] == ["api", "collector", "migrate"]


@pytest.mark.parametrize("enabled", ["false", "true"])
def test_load_balancers_flag_matches_manual_and_scheduled_collection(enabled: str) -> None:
    docs = render(f"collector.loadBalancersEnabled={enabled}")
    api = resource(docs, "Deployment", "cloudscope-api")["spec"]["template"]["spec"]
    cron = resource(docs, "CronJob", "cloudscope-collector")["spec"]["jobTemplate"]["spec"][
        "template"
    ]["spec"]
    for pod in (api, cron):
        env = {item["name"]: item for item in pod["containers"][0]["env"]}
        assert env["CLOUDSCOPE_LOAD_BALANCERS_ENABLED"]["value"] == enabled


@pytest.mark.parametrize("enabled", ["false", "true"])
def test_network_flag_matches_manual_and_scheduled_collection(enabled: str) -> None:
    docs = render(f"collector.networkEnabled={enabled}")
    api = resource(docs, "Deployment", "cloudscope-api")["spec"]["template"]["spec"]
    cron = resource(docs, "CronJob", "cloudscope-collector")["spec"]["jobTemplate"]["spec"][
        "template"
    ]["spec"]
    for pod in (api, cron):
        env = {item["name"]: item for item in pod["containers"][0]["env"]}
        assert env["CLOUDSCOPE_NETWORK_ENABLED"]["value"] == enabled


def test_missing_collection_flags_render_false() -> None:
    # `helm upgrade --reuse-values` keeps the old values, so a flag added in a newer chart is
    # missing. An empty string would stop the API at startup (not a valid boolean).
    docs = render("collector.networkEnabled=null", "collector.loadBalancersEnabled=null")
    api = resource(docs, "Deployment", "cloudscope-api")["spec"]["template"]["spec"]
    env = {item["name"]: item for item in api["containers"][0]["env"]}
    assert env["CLOUDSCOPE_NETWORK_ENABLED"]["value"] == "false"
    assert env["CLOUDSCOPE_LOAD_BALANCERS_ENABLED"]["value"] == "false"


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


@pytest.mark.parametrize("name", ["cloudscope", "custom-sa"])
def test_service_account_name_is_independent_of_release(name: str) -> None:
    settings = () if name == "cloudscope" else (f"serviceAccount.name={name}",)
    docs = render(*settings, release="other")
    resource(docs, "ServiceAccount", name)
    api = resource(docs, "Deployment", "other-api")["spec"]["template"]["spec"]
    cron = resource(docs, "CronJob", "other-collector")["spec"]["jobTemplate"]["spec"]
    assert api["serviceAccountName"] == name
    assert cron["template"]["spec"]["serviceAccountName"] == name


@pytest.mark.parametrize("kind", ["backend", "web"])
def test_empty_image_tag_is_rejected(kind: str) -> None:
    with pytest.raises(subprocess.CalledProcessError) as error:
        render(f"image.{kind}.tag=")
    assert f"set image.{kind}.tag to sha-<commit>" in error.value.stderr


def test_chart_secret_with_external_database_uses_post_install_pre_upgrade() -> None:
    docs = render(
        "postgres.enabled=false",
        "secrets.create=true",
        "secrets.data.DATABASE_URL=placeholder",
        "secrets.data.SECRET_KEY=placeholder",
    )
    job = resource(docs, "Job", "cloudscope-migrate")
    assert job["metadata"]["annotations"]["helm.sh/hook"] == "post-install,pre-upgrade"


def test_pods_disable_service_links() -> None:
    # The <release>-api Service would otherwise inject CLOUDSCOPE_API_PORT=tcp://...
    docs = render("api.forwardedAllowIPs=10.0.0.0/16")
    cron = resource(docs, "CronJob", "cloudscope-collector")["spec"]["jobTemplate"]["spec"]
    pods = [
        resource(docs, "Deployment", "cloudscope-api")["spec"]["template"]["spec"],
        resource(docs, "Deployment", "cloudscope-web")["spec"]["template"]["spec"],
        resource(docs, "StatefulSet", "cloudscope-postgres")["spec"]["template"]["spec"],
        resource(docs, "Job", "cloudscope-migrate")["spec"]["template"]["spec"],
        cron["template"]["spec"],
    ]
    assert all(pod["enableServiceLinks"] is False for pod in pods)


def test_dedicated_credentials_are_off_without_new_rbac() -> None:
    docs = render()
    assert not any(doc["kind"] in {"Namespace", "Role", "RoleBinding"} for doc in docs)


def test_dedicated_secret_rbac_tokens_and_network_boundary() -> None:
    docs = render(
        "accountCredentials.enabled=true", "accountCredentials.apiServerCIDRs[0]=10.0.0.1/32"
    )
    writer = resource(docs, "Role", "cloudscope-credential-writer")
    reader = resource(docs, "Role", "cloudscope-credential-reader")
    assert writer["metadata"]["namespace"] == "cloudscope-credentials"
    assert writer["rules"] == [{"apiGroups": [""], "resources": ["secrets"], "verbs": ["create"]}]
    assert reader["rules"][0]["verbs"] == ["get"]
    assert not any(doc["kind"] in {"ClusterRole", "ClusterRoleBinding"} for doc in docs)
    api = resource(docs, "Deployment", "cloudscope-api")["spec"]["template"]["spec"]
    collector = resource(docs, "CronJob", "cloudscope-collector")["spec"]["jobTemplate"]["spec"][
        "template"
    ]["spec"]
    for pod, name in [(api, "api"), (collector, "collector")]:
        assert pod["serviceAccountName"] == f"cloudscope-{name}-credentials"
        assert pod["automountServiceAccountToken"] is False
        token = next(v for v in pod["volumes"] if v["name"] == "credential-api-token")
        assert token["projected"]["sources"][0]["serviceAccountToken"]["expirationSeconds"] == 3600
    policy = resource(docs, "NetworkPolicy", "cloudscope-credential-egress")
    assert policy["spec"]["egress"][0]["to"] == [{"ipBlock": {"cidr": "10.0.0.1/32"}}]


def test_dedicated_credentials_create_their_namespace() -> None:
    docs = render(
        "accountCredentials.enabled=true", "accountCredentials.apiServerCIDRs[0]=10.0.0.1/32"
    )
    namespace = resource(docs, "Namespace", "cloudscope-credentials")
    assert namespace["metadata"]["annotations"] == {"helm.sh/resource-policy": "keep"}


def test_credentials_in_release_namespace_skip_namespace_object() -> None:
    docs = render(
        "accountCredentials.enabled=true",
        "accountCredentials.namespace=awsearch",
        "accountCredentials.apiServerCIDRs[0]=10.0.0.1/32",
        namespace="awsearch",
    )
    assert not any(doc["kind"] == "Namespace" for doc in docs)
    for name in ["cloudscope-credential-writer", "cloudscope-credential-reader"]:
        assert resource(docs, "Role", name)["metadata"]["namespace"] == "awsearch"
        assert resource(docs, "RoleBinding", name)["metadata"]["namespace"] == "awsearch"


def test_dedicated_credentials_require_explicit_api_server_network() -> None:
    with pytest.raises(subprocess.CalledProcessError):
        render("accountCredentials.enabled=true")
    with pytest.raises(subprocess.CalledProcessError):
        render("accountCredentials.enabled=true", "accountCredentials.apiServerCIDRs[0]=10.0.0.0/8")


@pytest.mark.parametrize("missing", [False, True])
def test_oidc_disabled_defaults_and_optional_secret(missing: bool) -> None:
    docs = render(*(["oidc=null", "publicUrl=null"] if missing else []))
    api = resource(docs, "Deployment", "cloudscope-api")["spec"]["template"]["spec"]
    env = {item["name"]: item for item in api["containers"][0]["env"]}
    assert env["CLOUDSCOPE_OIDC_ISSUER"]["value"] == ""
    assert env["CLOUDSCOPE_OIDC_CLIENT_ID"]["value"] == "cloudscope"
    assert env["CLOUDSCOPE_PUBLIC_URL"]["value"] == ""
    assert env["CLOUDSCOPE_OIDC_CLIENT_SECRET"]["valueFrom"]["secretKeyRef"] == {
        "name": "cloudscope",
        "key": "CLOUDSCOPE_OIDC_CLIENT_SECRET",
        "optional": True,
    }


def test_oidc_public_issuer_and_external_secret() -> None:
    docs = render(
        "oidc.issuer=https://idp.example.com/realms/team",
        "oidc.clientId=inventory",
        "publicUrl=https://inventory.example.com",
        "existingSecret=external-app-secret",
    )
    api = resource(docs, "Deployment", "cloudscope-api")["spec"]["template"]["spec"]
    env = {item["name"]: item for item in api["containers"][0]["env"]}
    assert env["CLOUDSCOPE_OIDC_ISSUER"]["value"] == "https://idp.example.com/realms/team"
    assert env["CLOUDSCOPE_OIDC_CLIENT_ID"]["value"] == "inventory"
    assert env["CLOUDSCOPE_PUBLIC_URL"]["value"] == "https://inventory.example.com"
    assert (
        env["CLOUDSCOPE_OIDC_CLIENT_SECRET"]["valueFrom"]["secretKeyRef"]["name"]
        == "external-app-secret"
    )
