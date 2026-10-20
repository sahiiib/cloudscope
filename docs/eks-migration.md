# Migration from the local cluster to EKS

Saheb, 2026-10-19. Move cloudscope from the local kubeadm cluster (namespace
`cloudscope`) to EKS cluster `eks-devops`, namespace `awsearch`. Done step by
step; each step ends with a check, and nothing in the local cluster changes
until the last step.

This is a **fresh install**: users, accounts and inventory are not copied from
the local cluster. The first admin is created again, accounts are added again
from the web panel, and the first sync fills the inventory.

## Status (2026-10-20)

The migration is done. The app runs only in `awsearch`: collection is on, the
web UI is reachable through a Cloudflare tunnel with Cloudflare Access in front
of it, and the team signs in with Keycloak SSO. Step 7 is postponed (see below).
The local cluster release and its namespaces were removed on 2026-10-20
(step 8). Deployment details (values, runbook) live in the private config repo.

Lessons from the first install:

- Image tags are `sha-<full 40-char commit sha>`; a short sha tag does not exist.
- GHCR images are private: the namespace needs a `ghcr-pull` Secret and
  `imagePullSecrets`.
- A failed first `helm install` leaves a failed release; uninstall it before
  installing again (the PVC and Secrets stay).

## What we know

| Topic | Answer (cluster admin, 2026-10-19) |
| --- | --- |
| Access | ServiceAccount `awsearch:saheb`, now with wide read access; cluster admin is coming. Rule from the admin: change nothing outside `awsearch`. |
| Kubernetes | EKS 1.34 in ap-southeast-1, in the team's own AWS account (it is also added to the inventory). `awsearch` is empty, no quota or LimitRange. |
| Storage | No default StorageClass. Admin asks for **EFS** (10Gi), not gp2/gp3. Postgres runs in-cluster, like the Keycloak database. |
| Ingress / TLS | None for now. Use `kubectl port-forward`; later Cloudflare (a `cloudflared` already runs in the cluster). |
| Images | Cluster can pull from GHCR. |
| Limits | None; the cluster is only used by the team. |
| Account keys | Same namespace (`awsearch`), no separate credentials namespace. |
| Pod Identity | The `eks-pod-identity-agent` runs on every node. The admin still creates the role and association (step 7). Until then, the base AWS key Secret. |
| Egress / NetworkPolicy | Outbound HTTPS to AWS (STS, EC2), Alibaba and GHCR works directly, no proxy (tested 2026-10-19). NetworkPolicies are **not enforced** (VPC CNI `--enable-network-policy=false`), so the chart's policies are inert until the admin turns enforcement on. |
| Admission webhook | `delete-interceptor` sees every CREATE/UPDATE/DELETE in every namespace with `failurePolicy: Fail`. Creating and deleting a test pod in `awsearch` worked. If that webhook is down, Helm installs and upgrades fail too. |

## Steps

### 0. Read-only checks (Saheb)

Done: egress test, webhook list, API endpoint addresses for `apiServerCIDRs`
(two private addresses; they can change when EKS replaces its control-plane
ENIs, which only matters once NetworkPolicies are enforced). Still to read: the
`delete-interceptor` webhook rules, and an existing EFS StorageClass plus the
Keycloak database PVC as a model for step 2.

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
image tags, `postgres.enabled: true`, `postgres.storageClass` set to the EFS
class,
`ingress.enabled: false`, `accountCredentials.namespace: awsearch`,
`collector.loadBalancersEnabled` and `collector.networkEnabled` as on the
local cluster, `collector.suspend: true` for the first install.

Check: `helm template -n awsearch` output reviewed together.

**EFS and Postgres.** The Postgres pod runs as uid/gid 999 and needs to own
its data directory. `fsGroup` does not change ownership on EFS (NFS), so the
StorageClass must create its access point with `uid: "999"`, `gid: "999"` and
`directoryPerms: "700"` (EFS CSI `provisioningMode: efs-ap`). The existing EFS
classes use a gid range (1000-2000), so files would belong to a random uid and
Postgres refuses to start ("wrong ownership"). Keycloak uses a static PV, which
the chart does not support. So a new class `cloudscope-efs` with
`reclaimPolicy: Retain`, fixed `uid`/`gid` 999 and its own `basePath` is created
by the admin, or by Saheb once cluster admin is granted.

### 3. Secrets in `awsearch` (Saheb)

- App Secret `cloudscope` with `DATABASE_URL`, `POSTGRES_PASSWORD` and a new
  `SECRET_KEY` (fresh install, so it does not need to match the local one).
- Base AWS and Alibaba keys (until Pod Identity is ready).
- Account key Secrets are not copied: the web panel creates them when
  accounts are added in step 5.

Commands are given at this step. No secret goes into chat or git.

Check: `kubectl -n awsearch get secrets` lists the expected names.

### 4. First install, collector off (Saheb)

`helm install` into `awsearch` with the values from step 2. The migrate hook
creates the schema up to the current head.

Check: api, web and postgres pods Ready; migrate Job succeeded;
`kubectl -n awsearch port-forward svc/cloudscope-web 8080:8080` opens the login page.

### 5. First admin and accounts (Saheb)

Create the first admin user with the CLI through `kubectl exec`, log in, turn
on MFA, then add the AWS and Alibaba accounts from the web panel (keys go
through the web form only).

Check: login with MFA works; every account shows "Test access OK".

### 6. Turn on collection (Saheb)

Set `collector.suspend: false`, run a manual sync for one account, then all.

Check: Sync page shows success for all regions; no `AccessDenied` or
network errors. If egress is blocked, stop here and go back to the admin.

### 7. Pod Identity (postponed)

Postponed on 2026-10-19 (Saheb): accounts connect with dedicated access keys
for now. The hub role can only assume `cloudscope-readonly` roles, so it is
useful only together with that role in the scanned accounts. When accounts
move to role-based access, do both at once: the admin creates `cloudscope-hub`
(`deploy/aws/hub-role.yaml` with `ServiceAccounts` set to
`cloudscope-api-credentials,cloudscope-collector-credentials`, because
`accountCredentials.enabled`) and one Pod Identity association per service
account, and each account gets `cloudscope-readonly`.

Check: an account set to "Assume Role" passes Test access with no static key.

### 8. Access and cut-over

Cloudflare tunnel to the EKS web Service (replaces port-forward; done, with
Cloudflare Access set up by the admin).

Cut-over, done 2026-10-20: with all accounts added on EKS, the last runs on
both clusters found the same 538 instances. The local collector was suspended,
a final `pg_dump -Fc` of the local database was kept on Saheb's machine, then
the local release, the `cloudscope` and `cloudscope-credentials` namespaces and
the temporary test tunnel were removed. The account keys were not rotated: EKS
uses the same keys.

## Later

- **SSO.** Done 2026-10-20 ([sso.md](specs/sso.md), T-083, T-084): the team
  signs in through the cluster's Keycloak; local password login is only for
  local admins. Lessons: the client-role mapper must have "Add to ID token" on
  (otherwise every user gets "Not authorized"), and Cloudflare in front of the
  issuer blocks the `Python-urllib` User-Agent (error 1010) but lets the API's
  httpx client through.

## Rollback

The local cluster is gone (step 8). A rollback on EKS is `helm -n awsearch
rollback cloudscope` to the previous revision; the local data survives only as
the final dump on Saheb's machine.
