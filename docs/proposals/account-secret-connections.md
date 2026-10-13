# Per-account credentials and adopting existing accounts (T-070)

Status: proposed for maintainer review. This document does not change the accepted
role/base-credentials design, deployed code, RBAC or stored data. It supersedes
the rejected database-key proposal #41 with a concrete Kubernetes Secret design.

## User requirement and current gap

The contributor needs to connect separate AWS and Alibaba test accounts from the
web console using an independent key pair for each account. The previous fork
provided that workflow, including adoption/editing of older accounts. Upstream
currently uses one runtime credential source per provider, optionally assuming
a role, and rejects editing file-managed accounts. The deployed database has
already been reconciled to `0006`; it must not be deleted or restored over newer
inventory just to recover the UI.

This is a product requirement, not a claim that a specific cloud account cannot
support AssumeRole. Keep role/runtime access as the preferred/default option.
Request explicit approval for independent Secret-backed connections when needed.

## Proposed user flow

1. Accounts lists every existing database account with name, alias, provider,
   enabled status, inventory count, configuration owner and connection mode.
2. Add/edit supports Runtime/Role and Dedicated credentials. AWS accepts access
   key ID, secret and optional session token; Alibaba accepts ID and secret.
   Inputs are write-only, masked, cleared after submission/cancel/navigation,
   and kept outside query/mutation caches and browser storage. Responses return
   only `credentials_configured`, never key values or partially masked keys.
3. File-managed rows remain read-only until an admin chooses **Manage in web**.
   Confirm that web configuration will take precedence over accounts.yaml;
   preserve provider/account identity, all inventory, aliases and sync history.
   Offer the current non-secret role/region values as defaults. There is no delete
   and recreate shortcut and no automatic conversion on migration.
4. Test access verifies caller identity matches the configured account and lists
   regions. A mismatch, expiration or denied access is actionable and sanitized.
   Collection uses that same validated identity path, including LB adapters.
5. Enable/disable keeps the existing explicit confirmation and retained inventory.

## Storage and isolation

- Database stores connection mode and a generated Secret reference only. No
  credentials, encrypted key blobs or serialized credential configurations.
- Use immutable, versioned Secrets in a dedicated namespace configured by the
  operator. The server generates names from provider/identity plus random version;
  users cannot nominate an arbitrary Secret or namespace to read through the app.
- Secret labels bind application/release, provider, account identity and version;
  validate binding on every read. Reject missing/malformed/mismatched Secrets.
- Kubernetes service-account TLS uses the mounted CA with verification. Never
  fall back to insecure TLS or an arbitrary client-supplied API endpoint.
- Separate API writer and collector reader service accounts. Namespace-scoped
  Roles only; no cluster-wide Secret permissions. Reader gets referenced Secrets
  by name; writer creates versions. No automatic Secret deletion, update of shared
  runtime Secrets or permission application during rollout.
- Kubernetes RBAC cannot restrict `create` by a name prefix. The dedicated
  namespace is therefore a required boundary; optional admission policy validates
  permitted names/labels and denies unrelated objects. Review this access change
  before enabling. Kubernetes Secrets are not encrypted at rest by default;
  operations must configure etcd encryption/access policy and private backups.
- EKS workload identity and existing shared runtime credentials remain supported.
  Local development uses an injected private local adapter with equivalent binding
  and permissions, never a hardcoded or publicly readable credential file.

## Atomicity, rotation and collection

1. Create a new immutable Secret version, without changing the active reference.
2. Validate access and provider/account binding; failures leave the active account
   and existing inventory untouched.
3. Take the existing collection advisory lock and database row lock, then update
   the active reference and non-secret configuration in one transaction. Reject
   concurrent edits using an expected configuration version (409, refresh/retry).
4. On database failure, leave the prior reference active. Tag the unreferenced
   version for operator cleanup; do not compensate by deleting a shared Secret.
5. Cache credentials only in memory, keyed by immutable reference/version and STS
   expiry. Rotation changes the reference, invalidating cached sessions naturally.

Secrets are not read in API listing/detail responses. Raw SDK exceptions, request
bodies, keys, tokens and Secret contents must never appear in logs or errors.
Audit actor/action/provider/count or a safe identity identifier only.

## Forward migration and rollout

Allocate a new unique migration after the then-current upstream head (coordinate
with T-069's `0007`). Add nullable Secret reference, default Runtime mode and
configuration version. Existing rows stay unchanged and no keys are recovered or
silently discarded. API/collector readers must reject Dedicated mode without a
valid reference instead of falling back to runtime credentials.

Maintain a compatibility gate: once a Dedicated connection is enabled, an older
image must not scan it using the base credential source. Pause collection and
disable Dedicated rows before an older-image rollback, or use a reviewed forward
fix. A Helm rollback cannot restore the previous schema or credential material.

Operator sequence: review design, implement/test a separate task, back up the
current DB + runtime and per-account Secrets, restore-test in isolation, verify
old account/inventory/MFA preservation, apply approved namespace/RBAC, migrate,
deploy the same tested image digests, adopt one disabled test account, enter/test
its keys, then enable collection. Do not recover old keys from a historical backup
without checking rotation/expiry and authorization; entering current keys is safer.

## Required implementation tests

- API: admin/full session/CSRF, write-only keys, provider-specific validation,
  invalid-field redaction, response/log/cache absence of credential values.
- Adoption: file to UI with explicit confirmation, identity immutability,
  retained accounts/instances/LBs/history, UI precedence on the next file sync.
- Secret adapter: verified TLS, namespace/name/label binding, denied/missing
  Secret, separate reader/writer contracts, no arbitrary Secret lookup.
- Rotation: validated identity, rollback on validation/DB failure, simultaneous
  edits and collector lock, old reference retained, versioned in-memory cache.
- Providers: AWS STS identity/expiry and Alibaba STS caller identity with fakes;
  every EC2/ECS/LB call uses the selected account's connection. No live cloud tests.
- Migration: fresh and deployed `0006`/later schemas preserve all existing data.
- UI: old account adoption, add/edit key mode per provider, cleared input values,
  validation/error states, no key echo and accessible light/dark presentation.

## Decisions requested from Saheb

1. Approve Dedicated credentials as an optional Secret-backed mode for the stated
   test-account workflow, retaining Runtime/Role as default.
2. Approve explicit file-account adoption into web ownership without deleting data.
3. Choose the dedicated Secret namespace, API writer boundary/admission policy and
   local-development adapter before enabling any new RBAC or shared deployment.

Only after those decisions, register the implementation task/spec changes and
submit its code PR. T-070 is the reviewable design task, not a claim that the feature
has been restored on the cluster.

References: [Kubernetes Secret guidance](https://kubernetes.io/docs/concepts/security/secrets-good-practices/)
and [RBAC resource-name restrictions](https://kubernetes.io/docs/reference/access-authn-authz/rbac/#referring-to-resources).
