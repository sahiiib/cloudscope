# CloudScope Helm chart (T-041)

Render before installing:

```sh
helm lint deploy/helm/cloudscope -f values.local.yaml
helm template cloudscope deploy/helm/cloudscope -f values.local.yaml
helm upgrade --install cloudscope deploy/helm/cloudscope \
  --namespace cloudscope --create-namespace --wait --timeout 10m -f values.local.yaml
```

Keep local values containing account configuration or secrets outside Git. Use
immutable `sha-<full-commit-sha>` tags in `image.backend.tag` and `image.web.tag`
in values.local.yaml (or pass both with `--set`). Both default to empty and
rendering fails until explicitly supplied. Resource names use the release name
(e.g. `cloudscope-api`), except the ServiceAccount.

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
- `serviceAccount.name`: defaults to `cloudscope`, independent of the release
  name, matching the AWS hub role trust. Changing it requires matching IAM trust
  and workload identity configuration.
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

With an external database and existing Secret, migrations use
`pre-install,pre-upgrade`. When PostgreSQL or the Secret is chart-managed, they
use `post-install,pre-upgrade`: only first install migrates after rollout, since
those resources do not exist beforehand. All normal upgrades migrate before
rolling out the new application. On first install, wait for the hook to finish
before using the application. A bounded database readiness check precedes
`alembic upgrade head`; Helm fails the release if migration fails. Successful
hook Jobs are deleted; failed Jobs remain for inspection.

Two upgrade edge cases require separate planning:

- Changing a chart-managed DATABASE_URL Secret in the same upgrade: the
  pre-upgrade Job reads the **old** Secret value, because Helm has not applied
  the new Secret yet. Prepare the target database and migrate it explicitly
  before switching the application's URL; do not rely on that hook to migrate
  the new target. For an existing external Secret, the Job reads whichever
  value is already present when it starts.
- Switching `postgres.enabled` from `false` to `true` on upgrade is unsupported:
  the new PostgreSQL resources are not available to the pre-upgrade hook.
  Provision/migrate the database separately or perform a planned new install
  and data transfer; do not toggle this value on an existing release.

The chart does not create the initial admin. After a successful install:

```sh
kubectl -n cloudscope exec -it deploy/cloudscope-api -- cloudscope create-user admin --admin
```

CI lints and renders the chart and checks internal/external DB, Secret, ingress,
identity, network isolation and migration wiring. A real cluster/storage/ingress
installation is covered by T-042; rendering does not verify those integrations.

### Elastic IP inventory (T-081)

`collector.networkEnabled` defaults to `false` and sets
`CLOUDSCOPE_NETWORK_ENABLED` for both API/manual sync and the collector CronJob.
Apply additive migration `0012` before running the new image. Grant AWS
`ec2:DescribeAddresses` or Alibaba `vpc:DescribeEipAddresses` (included in
`AliyunVPCReadOnlyAccess`) before enabling. Scan errors retain earlier inventory;
check **Elastic IPs → Collection status** after sync. The flag will also cover
NAT gateways in T-082; it does not enable them in this increment.
