# Deployment

## Images

One backend image, one frontend image, both built by CI and pushed to GHCR
(`ghcr.io/sahiiib/cloudscope-backend`, `ghcr.io/sahiiib/cloudscope-web`).

- **backend**: `python:3.12-slim`, `uv sync --frozen --no-dev`, non-root user,
  entrypoint `cloudscope`. Command `api` (uvicorn, port 8000) or `collect`.
- **web**: multi-stage: `node:20` build → `nginxinc/nginx-unprivileged`, serves
  the SPA on port 8080 and proxies `/api` to the API service.

Images are multi-arch (`linux/amd64`, `linux/arm64`).

## Helm chart (`deploy/helm/cloudscope`)

| Resource | Notes |
| --- | --- |
| `Deployment` api | 2 replicas, readiness `/readyz`, liveness `/healthz` |
| `Deployment` web | 2 replicas |
| `CronJob` collector | `*/15 * * * *`, `concurrencyPolicy: Forbid`, `backoffLimit: 1` |
| `Job` migrate | Helm `pre-install,pre-upgrade` hook: `alembic upgrade head` |
| `StatefulSet` postgres | Only when `postgres.enabled=true` (official `postgres:16` image, PVC) |
| `ConfigMap` accounts | From `values.accounts` → `accounts.yaml` |
| `Secret` | Only created when `secrets.create=true`; otherwise reference `existingSecret` |
| `Ingress` | Optional, class configurable |
| `ServiceAccount` | Annotations configurable (for IRSA) |
| `NetworkPolicy` | Postgres only reachable from api, collector, migrate |

Key values:

```yaml
image:
  backend: {repository: ghcr.io/sahiiib/cloudscope-backend, tag: ""}
  web:     {repository: ghcr.io/sahiiib/cloudscope-web, tag: ""}
collector:
  schedule: "*/15 * * * *"
  concurrency: 8
accounts: []                 # same shape as accounts.yaml
existingSecret: cloudscope   # keys below
# Secret keys: DATABASE_URL, SECRET_KEY, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY,
#              ALIBABA_CLOUD_ACCESS_KEY_ID, ALIBABA_CLOUD_ACCESS_KEY_SECRET
postgres:
  enabled: true
  storageClass: ""
  size: 10Gi
serviceAccount:
  annotations: {}            # eks.amazonaws.com/role-arn for IRSA
ingress:
  enabled: false
  className: nginx
  host: cloudscope.local
  tls: []
```

## Local cluster (kubeadm, 3 nodes on Proxmox)

1. **Storage**: if the cluster has no default StorageClass, install
   `rancher/local-path-provisioner` (simple, node-local) or Longhorn
   (replicated across the 3 nodes, recommended if the data should survive a
   node loss). Set `postgres.storageClass` accordingly.
2. **Ingress**: ingress-nginx with a NodePort or MetalLB; or use
   `kubectl port-forward` to start.
3. **Credentials**: create the secret by hand from the test keys, never from a
   file in the repo:
   ```bash
   kubectl create namespace cloudscope
   kubectl -n cloudscope create secret generic cloudscope \
     --from-literal=DATABASE_URL='postgresql+psycopg://cloudscope:...@cloudscope-postgres:5432/cloudscope' \
     --from-literal=SECRET_KEY="$(python -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())')" \
     --from-literal=AWS_ACCESS_KEY_ID=... --from-literal=AWS_SECRET_ACCESS_KEY=... \
     --from-literal=ALIBABA_CLOUD_ACCESS_KEY_ID=... --from-literal=ALIBABA_CLOUD_ACCESS_KEY_SECRET=...
   ```
4. `helm install cloudscope deploy/helm/cloudscope -n cloudscope -f values.local.yaml`
5. `kubectl -n cloudscope exec deploy/cloudscope-api -- cloudscope create-user admin --admin`

## EKS (production)

- AWS credentials: no static keys. The collector ServiceAccount gets the hub
  role via EKS Pod Identity (preferred) or IRSA; the hub role may only
  `sts:AssumeRole` into `cloudscope-readonly` roles. See
  [cloud-access.md](cloud-access.md).
- Alibaba key: stored in AWS Secrets Manager, synced into the `cloudscope`
  Secret by External Secrets Operator (or created by hand at first).
- Database: in-cluster StatefulSet or RDS PostgreSQL (`postgres.enabled=false`,
  `DATABASE_URL` points at RDS).
- Ingress: AWS Load Balancer Controller, internal ALB, TLS via ACM.
