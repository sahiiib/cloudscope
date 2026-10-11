# EKS values (T-053)

These are deployment examples, not a provisioner. No AWS resources are created by
rendering them. Replace every placeholder in a private copy before deployment.
Cloud inventory access stays read-only; the human rollout in T-052 prepares the
roles and account list. Do not put credentials in values or commit local copies.

## Prerequisites and identities

Use an existing EKS cluster with the Pod Identity Agent, AWS Load Balancer
Controller, a NetworkPolicy-capable CNI, and External Secrets Operator (ESO) with
`external-secrets.io/v1` CRDs. Private subnets need outbound access or suitable
endpoints for EKS Auth, STS, Secrets Manager, EC2, the registry and Alibaba APIs.
Set the namespace to `cloudscope` (or update both the IAM trust and examples).

Configure these **separate** Pod Identity associations in EKS:

| Namespace / ServiceAccount | IAM role | Permissions |
| --- | --- | --- |
| `cloudscope` / `cloudscope` | `cloudscope-hub` from T-050 | Only assume target `cloudscope-readonly` roles |
| ESO controller namespace / actual controller ServiceAccount | Dedicated ESO reader role | Read only the `cloudscope/prod` secret |

For each role, trust `pods.eks.amazonaws.com` for `sts:AssumeRole` and
`sts:TagSession`, scoped to the cluster ARN, namespace and ServiceAccount session
tags. Keep session tags enabled. The hub trust already does this; configure the
ESO role for its own controller identity. Pod Identity uses EKS associations,
not `eks.amazonaws.com/role-arn` annotations. The chart gives API and collector
the `cloudscope` ServiceAccount, supporting scheduled and manual collection.
Do not inject static AWS access keys into the CloudScope Secret.

[Pod Identity association documentation](https://docs.aws.amazon.com/eks/latest/userguide/pod-id-association.html)
explains the cluster-side association. The
[ESO AWS authentication documentation](https://external-secrets.io/latest/provider/aws-access/)
uses the controller's identity and disallows `serviceAccountRef` with Pod Identity.
Accordingly, the SecretStore has no `auth` block. The hub role receives no Secrets
Manager permissions. Scope the separate ESO role with
[`eso-read-policy.json`](../deploy/eks/eso-read-policy.json), replacing the region
and account. If using a customer-managed KMS key, also grant `kms:Decrypt` only on
that key, restricted through Secrets Manager, and allow that role in the key policy.
Use a dedicated ESO controller or restrict who may create SecretStores and
ExternalSecrets; the controller identity can read the secret it is allowed.

## Runtime secret and database

An administrator stores one JSON secret named `cloudscope/prod` in Secrets
Manager with these properties (values never belong in the repository):

- `DATABASE_URL`: a complete SQLAlchemy psycopg URL. RDS example with placeholders:
  `postgresql+psycopg://cloudscope:REPLACE_WITH_URL_ENCODED_PASSWORD@db.example.eu-central-1.rds.amazonaws.com:5432/cloudscope?sslmode=require`.
- `SECRET_KEY`: a persistent Fernet key; keep it stable across releases so existing
  TOTP enrollment remains decryptable.
- `ALIBABA_CLOUD_ACCESS_KEY_ID` and `ALIBABA_CLOUD_ACCESS_KEY_SECRET`: central RAM
  user's assume-role credentials from T-051/T-052.

Create the database and application DB user beforehand. URL-encode the password;
allow port 5432 only from application/migration workloads through the RDS security
group. RDS should be private and reachable from the cluster. `sslmode=require`
encrypts the connection but does not require hostname verification. For verified
TLS, include the AWS RDS CA bundle in your backend image and use
`sslmode=verify-full&sslrootcert=/path/to/rds-ca-bundle.pem` in DATABASE_URL; the
same image is used by API, collector and migration. Follow the
[RDS PostgreSQL TLS guide](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/PostgreSQL.Concepts.General.SSL.html).
This example uses password authentication, not short-lived RDS IAM auth tokens.

Apply [`external-secret.yaml`](../deploy/eks/external-secret.yaml) to an existing
namespace **before** installing the application, and wait without printing values:

```sh
kubectl apply -f /private/path/external-secret.yaml
kubectl -n cloudscope wait --for=condition=Ready secretstore/cloudscope-aws --timeout=120s
kubectl -n cloudscope wait --for=condition=Ready externalsecret/cloudscope --timeout=120s
```

The manifest explicitly maps four properties, so unrelated keys (especially AWS
static credentials) are not imported. `existingSecret: cloudscope` and
`secrets.create: false` prevent Helm from owning or overwriting it. ESO refreshes
every hour. `deletionPolicy: Retain` retains the target if provider data vanishes;
`creationPolicy: Owner` still means deleting the ExternalSecret deletes its owned
Kubernetes Secret. Protect both resources against accidental deletion.

The RDS values set `postgres.enabled: false`; migrations are pre-install and
pre-upgrade and need the external Secret and DB ready first. When changing the
URL, synchronize the Secret before upgrade and prepare/migrate the target DB;
review [migration ordering](../deploy/helm/cloudscope/README.md#migration-order).
Secret env vars do not hot-reload: restart API pods after a credential rotation;
new collector Jobs read the current Secret. Coordinate password rotation with
running jobs and keep SECRET_KEY stable.

### In-cluster PostgreSQL alternative

Choose this on the **first install** by overriding `postgres.enabled: true`,
`postgres.storageClass` (an installed EBS CSI StorageClass) and `postgres.size`.
Set DATABASE_URL to `postgresql+psycopg://cloudscope:...@cloudscope-postgres:5432/cloudscope`
for release `cloudscope`, and add a matching `POSTGRES_PASSWORD` property in
Secrets Manager. Append this mapping to the ExternalSecret's `spec.data`:

```yaml
- secretKey: POSTGRES_PASSWORD
  remoteRef:
    key: cloudscope/prod
    property: POSTGRES_PASSWORD
```

Wait for ESO readiness again before installation. This mode uses post-install,
pre-upgrade migrations and persistent storage. Do not switch `postgres.enabled`
from false to true on an existing release; use a planned database migration/new
install. Changing from internal DB to RDS also requires an explicit data transfer
and cutover, not just toggling a value.

## ALB, proxy trust and deployment

[`values.eks.yaml`](../deploy/helm/values.eks.yaml) targets an **internal** ALB in
IP mode, forwarding to web port 8080. Replace the hostname, ACM certificate ARN,
allowed client CIDRs and proxy CIDRs. ACM terminates HTTPS; HTTP redirects to 443,
and secure cookies remain enabled. No Kubernetes TLS Secret is needed. Configure
private DNS to point the hostname to the ALB and restrict its security group to
intended clients. See the [controller annotations](https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/guide/ingress/annotations/).

Set `api.forwardedAllowIPs` to the actual web pod and ALB subnet CIDRs, never `*`.
`10.0.0.0/16` is only a placeholder. ALB appends the real client to X-Forwarded-For;
nginx appends the ALB peer, and uvicorn walks past trusted proxies to the client.
Do not include untrusted client ranges as trusted proxies. Restrict direct web
pod access to the ALB with your pod/node security groups; the chart's API
NetworkPolicy permits only web pods. Verify individual client IPs and HTTPS
handling in the deployed cluster before opening access.

Keep both image tags pinned to the same published `sha-<full-commit-sha>`. Tags
are intentionally empty in the example and rendering fails until supplied.
Replace the sample account IDs/roles with the completed T-052 inventory; AWS
assumed roles require `external_id: cloudscope`.

```sh
helm lint deploy/helm/cloudscope -f /private/path/values.eks.yaml
helm template cloudscope deploy/helm/cloudscope -n cloudscope -f /private/path/values.eks.yaml
helm upgrade --install cloudscope deploy/helm/cloudscope -n cloudscope \
  -f /private/path/values.eks.yaml --wait --timeout 10m
```

After successful migration, create the initial administrator interactively using
`kubectl -n cloudscope exec -it deploy/cloudscope-api -- cloudscope create-user admin --admin`.
Validate login/MFA, distinct-client rate-limit behavior, manual sync and a scheduled
collector run. Local tests only validate manifests/rendering; they do not verify
live EKS identity, ACM, DNS, RDS connectivity or ESO reconciliation.
