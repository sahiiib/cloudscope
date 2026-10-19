# Migration from the local cluster to EKS

Saheb, 2026-10-19. Move cloudscope from the local kubeadm cluster (namespace
`cloudscope`) to EKS cluster `eks-devops`, namespace `awsearch`. Done step by
step; each step ends with a check, and nothing in the local cluster changes
until the last step.

## What we know

| Topic | Answer (cluster admin, 2026-10-19) |
| --- | --- |
| Access | ServiceAccount `awsearch:saheb`, namespace-scoped. Can create Deployments, StatefulSets, Jobs, CronJobs, Services, PVCs, Secrets, ServiceAccounts, Roles/RoleBindings, NetworkPolicies, port-forward and exec. No cluster-scoped reads or writes. |
| Kubernetes | EKS 1.34. `awsearch` is empty, no quota or LimitRange. |
| Storage | Default StorageClass is fine; in-cluster PostgreSQL (10Gi PVC) is OK. |
| Ingress / TLS | None for now. Use `kubectl port-forward`; later a Cloudflare tunnel, as on the local cluster. |
| Images | Cluster can pull from GHCR. |
| Limits | None; the cluster is only used by the team. |
| Account keys | Same namespace (`awsearch`), no separate credentials namespace. |
| Pod Identity / IRSA | **Open**: admin is checking. Until then, the base AWS key Secret, as today. |
| Egress / NetworkPolicy | **Open**: admin is checking whether NetworkPolicies are enforced and outbound access to AWS and Alibaba APIs works. |

## Steps

### 1. Chart changes for a single namespace (Claude, PR)

The chart can't be installed in `awsearch` as it is:

- With `accountCredentials.enabled`, it always creates the credentials
  `Namespace`. We have no permission for that, and here the namespace already
  exists. Fix: skip the Namespace when `accountCredentials.namespace` equals the
  release namespace.
- In the same namespace, the credential reader Role (`get` on Secrets) can read
  every Secret in `awsearch`, not only account keys. That includes the app
  Secret and Helm release Secrets. This is the trade-off of option 8 and is
  documented; a dedicated namespace stays the safer choice when one becomes
  available.
- `accountCredentials.apiServerCIDRs` must list the EKS API endpoint addresses.
  The admin gives these together with the egress answer.

Check: `helm template` renders with no Namespace and no cluster-scoped object.

### 2. Values file for EKS (Claude)

`values-eks-awsearch.yaml` (not committed if it holds anything private):
image tags, `postgres.enabled: true`, default StorageClass,
`ingress.enabled: false`, `accountCredentials.namespace: awsearch`,
`collector.loadBalancersEnabled` and `collector.networkEnabled` as on the
local cluster, `collector.suspend: true` for the first install.

Check: `helm template -n awsearch` output reviewed together.

### 3. Secrets in `awsearch` (Saheb)

- App Secret `cloudscope` with `DATABASE_URL`, `POSTGRES_PASSWORD` and the
  **same `SECRET_KEY` as the local cluster**. A new key can't decrypt the
  stored TOTP secrets, so every user's MFA would break.
- Base AWS and Alibaba keys (until Pod Identity is ready).
- Account key Secrets (`cs-…`) copied from `cloudscope-credentials` with the
  same names and labels; only the namespace changes.

Commands are given at this step. No secret goes into chat or git.

Check: `kubectl -n awsearch get secrets` lists the expected names.

### 4. First install, collector off (Saheb)

`helm install` into `awsearch` with the values from step 2. The migrate hook
creates the schema up to the current head.

Check: api, web and postgres pods Ready; migrate Job succeeded;
`kubectl -n awsearch port-forward svc/cloudscope-web 8080:8080` opens the login page.

### 5. Copy the database (Saheb)

1. On the local cluster: suspend the collector CronJob, then `pg_dump -Fc`.
2. On EKS: scale api to 0, `pg_restore --clean` into the EKS Postgres
   (through `kubectl exec`), scale api back.

Check: log in with the existing admin user and MFA; instance, LB, EIP and NAT
counts match the local cluster.

### 6. Turn on collection (Saheb)

Set `collector.suspend: false`, run a manual sync for one account.

Check: Sync page shows success for all regions; no `AccessDenied` or
network errors. If egress is blocked, stop here and go back to the admin.

### 7. Pod Identity (when the admin is ready)

Admin creates the `cloudscope-hub` role and the association for the
`cloudscope` ServiceAccount. Then remove the base AWS key from the Secret.

Check: sync still succeeds with no static AWS key.

### 8. Access and cut-over

Cloudflare tunnel to the EKS web Service (replaces port-forward). After a few
days of parallel running, suspend the local collector and keep a final local
dump as backup before removing the local release.

## Rollback

Until step 8 the local cluster keeps running unchanged, so rollback is
`helm uninstall` in `awsearch` (the PVC and Secrets are deleted separately
only when we decide to).
