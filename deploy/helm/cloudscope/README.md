# CloudScope Helm chart (T-041)

Render before installing:

```sh
helm lint deploy/helm/cloudscope
helm template cloudscope deploy/helm/cloudscope -f values.local.yaml
helm upgrade --install cloudscope deploy/helm/cloudscope \
  --namespace cloudscope --create-namespace --wait --timeout 10m -f values.local.yaml
```

Keep local values containing account configuration or secrets outside Git. Use
immutable `sha-<full-commit-sha>` image tags for both images; `latest` is only a
convenience default. Resource names use the release name (e.g. `cloudscope-api`).

## Configuration

- `accounts`: the list from accounts.yaml, mounted read-only into API/collector.
- `existingSecret`: pre-created, same-namespace Secret, default `cloudscope`.
  Required keys: `DATABASE_URL`, `SECRET_KEY`; also `POSTGRES_PASSWORD` for the
  internal PostgreSQL. DATABASE_URL must use `postgresql+psycopg://`, and point
  to `<release>-postgres:5432/cloudscope` for the internal database. Its password
  must match POSTGRES_PASSWORD. SECRET_KEY is a Fernet key, generated outside Git.
- Optional Secret keys: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
  `AWS_SESSION_TOKEN`, `ALIBABA_CLOUD_ACCESS_KEY_ID`,
  `ALIBABA_CLOUD_ACCESS_KEY_SECRET`. Omit AWS keys when using workload identity.
- `secrets.create: true`: create the Secret from `secrets.data` instead. These
  values are stored in Helm release metadata; prefer an externally managed Secret.
- `api.forwardedAllowIPs`: **set to your web/ingress pod CIDRs**, comma-separated.
  Never `*` (the chart rejects it). The loopback default trusts no remote proxy.
  The ingress must sanitize incoming forwarded headers. The API NetworkPolicy
  only admits web pods; use a CNI that enforces NetworkPolicy.
- `postgres.enabled: false`: omit PostgreSQL/PVC and use an external DATABASE_URL.
  With internal PostgreSQL, set `postgres.storageClass` if no default exists;
  `postgres.size` defaults to 10Gi. PVC data survives StatefulSet removal.
- `serviceAccount.annotations`: IRSA / workload identity annotations. API and
  collector use this ServiceAccount; no Kubernetes API permissions are granted.
- `ingress.enabled`, `className`, `annotations`, `host`, `tls`: expose web through
  your installed controller. Secure cookies default on; use TLS. For local HTTP
  testing only, explicitly set `api.cookieSecure: false`.
- `imagePullSecrets`: list of `{name: registry-secret}` references, pre-created.
- `collector.schedule`, `concurrency`, `suspend`: scheduled collection controls.
  CronJob concurrency is Forbid; the application's database lock also prevents
  overlap with manual runs.
- `resources`: requests/limits for each workload. All run non-root; the web pod
  mounts writable emptyDirs on `/etc/nginx/conf.d` and `/tmp` for its read-only root.

## Migration order

With an external database and existing Secret, migrations use the specified
`pre-install,pre-upgrade` hooks. When the chart creates PostgreSQL or the Secret,
use `post-install,post-upgrade` instead: a pre-install hook cannot access resources
that Helm has not created yet. A bounded database readiness init container runs
before `alembic upgrade head`; Helm waits for migration completion and fails the
release if it fails. Successful hook Jobs are deleted, failed Jobs remain for
inspection. Existing applications may briefly run before the post-upgrade
migration: use external/pre-provisioned resources if migration-before-rollout is
required. This is an explicit bootstrap deviation from the deployment spec,
following [Helm hook ordering](https://helm.sh/docs/topics/charts_hooks/).

The chart does not create the initial admin. After a successful install:

```sh
kubectl -n cloudscope exec -it deploy/cloudscope-api -- cloudscope create-user admin --admin
```

CI lints and renders the chart and checks internal/external DB, Secret, ingress,
identity, network isolation and migration wiring. A real cluster/storage/ingress
installation is covered by T-042; rendering does not verify those integrations.
