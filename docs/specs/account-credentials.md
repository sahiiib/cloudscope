# Dedicated account credentials and adoption — T-071

Assigned by the contributor. Product decisions approved by Saheb in
[PR #48](https://github.com/sahiiib/cloudscope/pull/48#issuecomment-6145956330)
on 2026-10-13: optional Dedicated credentials, namespace
`cloudscope-credentials`, explicit file-to-web adoption without data loss.
This implementation extends [accounts.md](accounts.md), retaining Runtime/Role
as default. Deployment remains subject to code/RBAC review.

## Web flow and API

- Accounts lists every database account, its source, connection mode and inventory.
  File accounts offer **Manage in web** with explicit confirmation. Adoption changes
  only ownership/version; identity, enabled state, alias, inventory and history stay.
  UI ownership takes precedence on subsequent file syncs.
- Add/edit has Runtime credentials, Assume Role and Dedicated Access Key choices.
  Dedicated keys are provider-specific: AWS ID/secret/optional session token;
  Alibaba ID/secret. Never combine a dedicated key with a role or external ID.
  Keep a saved key by leaving inputs blank; enter both fields to rotate.
- Key inputs are masked and write-only, outside query/mutation variables/storage.
  Clear on submission, provider/method change, cancel and navigation. Never return
  keys, partial key values or Secret names. Return `credentials_configured` only.
- `GET /api/accounts/capabilities` is admin-only and returns the feature flag.
  List/write responses add `connection_mode`, `configuration_version` and
  `credentials_configured`. Member list access remains unchanged.
- Create accepts `connection_mode` (default runtime) and optional `credentials`.
  Dedicated creation requires a key pair. PATCH accepts those plus
  `expected_version`; require a current version for connection changes. Every
  changed UI row increments its version; stale writes return 409. Legacy metadata
  PATCH clients remain supported, but still check the version observed on read.
- `POST /api/accounts/{provider}/{account_id}/adopt` requires
  `{confirmed: true, expected_version}`. Existing admin/full-session/CSRF checks
  apply to every write and access test.

## Storage, identity and concurrency

Migration 0008 follows LB migration 0007. It adds default Runtime mode, nullable
generated Secret reference and configuration version; existing rows stay unchanged.
No database key material, old key recovery, inventory deletion or recreation.

The server generates an immutable version (`cs-<random uuid>`). Labels bind owner,
provider and a hash of account identity. References must match the generated format;
all reads verify type, immutability and labels. The namespace and owner are operator
configuration, never client input. Kubernetes HTTPS REST uses the mounted CA,
rotating projected token and a bounded timeout/response; no redirects or insecure TLS.
Standard-library HTTP avoids a new client dependency.

Validate new versions with the collector's access service before changing the DB.
AWS STS GetCallerIdentity `Account` / Alibaba STS GetCallerIdentity `AccountId`
must equal the configured identity before EC2/ECS/LB use. SDK clients use the
selected account credentials and fail closed on missing/disabled/invalid Secrets.
Never fall back from Dedicated to the shared runtime keys. Cache verified sessions
only in process memory using account identity and immutable version.

After validation, acquire the existing global collection advisory lock and row lock,
check the configuration version, and change the reference/config in one transaction.
Collection in progress returns 409. Validation/store/DB failure leaves the old
reference and inventory intact; unreferenced immutable versions are retained for
operator cleanup. No Secret deletion/update/list permissions or automatic cleanup.

## Helm and review decisions

`accountCredentials.enabled` defaults false; namespace, service accounts, Roles,
bindings, token mounts and egress policy are created only when explicitly enabled.
The existing `accounts` Helm value is a list, so nesting
`accounts.dedicatedCredentials.enabled` would change its type and break installs.
Saheb confirmed this key in PR #49; the existing list is unchanged.

Writer Role permits create; reader Role permits get. Collector receives reader only.
The API receives writer **and reader** bindings: it already runs manual collection
and must test existing connections after restart. This necessary read permission is
an explicit extension to the initial review's create-only API boundary, approved
by Saheb on 2026-10-14 in [PR #49](https://github.com/sahiiib/cloudscope/pull/49#issuecomment-6162205362).
No cluster-wide permissions.

Require explicit API-server /32 addresses and HTTPS port; account for CNI DNAT to
the Service/endpoint IPs. Egress also permits DNS, same-release PostgreSQL and
public cloud HTTPS, excluding private/link-local ranges. Configure reviewed
`databaseCIDRs` for private RDS and `extraEgress` for private cloud/workload identity
endpoints or nonstandard DNS. Confirm the CNI enforces the policy. New service
accounts need their own EKS Pod Identity associations; preserve existing annotations
for IRSA. No broad private-network exception is implicit.

For a kubeadm CNI evaluating egress after Service DNAT (for example the applicable
Calico/Cilium configuration), use the control-plane node IP and port 6443:

```yaml
accountCredentials:
  enabled: true
  namespace: cloudscope-credentials
  apiServerCIDRs: ["10.0.0.1/32"] # Replace with the control-plane endpoint(s).
  apiServerPort: 6443
```

The default Service port 443 does not match the post-DNAT endpoint in that case.
Verify the cluster CNI's evaluation point and configure only the required endpoints.

When the cluster gives the app only one namespace, `accountCredentials.namespace`
may equal the release namespace. The chart then creates no `Namespace` object
(nothing cluster-scoped) and puts the writer/reader Roles in the release
namespace. Trade-off: the reader Role's `get` on Secrets then covers every
Secret in that namespace (the app Secret and Helm release Secrets included),
not only account keys. Use a dedicated namespace whenever one is available.

Old immutable versions are kept intentionally. For release `cloudscope`, an
operator can list names only (replace the label value for another release):

```shell
kubectl -n cloudscope-credentials get secrets -l cloudscope.io/owner=cloudscope -o custom-columns=NAME:.metadata.name --no-headers
```

Subtract the non-null `SELECT credential_reference FROM accounts` references.
Review unreferenced names
against in-flight jobs and backups before manual cleanup; do not grant the app list
or delete permissions or delete anything automatically.

Configure etcd encryption, dedicated namespace access and private backups before
entering real keys. Local development can explicitly use a private operator-owned
directory via `CLOUDSCOPE_LOCAL_CREDENTIALS_DIRECTORY`; require POSIX mode 0700,
or restrictive Windows ACLs. Local adapter is forbidden in Kubernetes. Do not put
the directory in the source tree or use real keys in automated tests.

## Promotion and rollback

Review code/RBAC, build immutable images, back up DB/runtime/per-account Secrets,
restore-test the backup and migration in isolation, deploy with the feature off,
then apply approved namespace/RBAC/network values and verify connectivity. Adopt a
disabled test account, enter its current keys, test identity, then enable collection.

Before an image lacking this feature is used, pause collection and disable all
Dedicated rows; old collectors do not understand references and would use runtime
credentials. Prefer a forward fix. Helm rollback does not roll back schema/keys.
Migration downgrade refuses while any Dedicated references remain; explicit switch
to Runtime is required first. Never restore an older database over newer inventory.

Tests cover identity/isolation, absence of keys in responses/logs/browser caches,
failed rotation and stale edits, Secret bindings/HTTPS errors, adoption preserving
inventory/LBs/history, migration preservation and downgrade guard, and off/enabled
Helm RBAC/network wiring. Tests use fakes/moto, never live cloud APIs.
