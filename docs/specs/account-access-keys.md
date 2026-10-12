# Proposal: preserve per-account access keys and web adoption (T-065)

Status: **review proposal, not implemented or approved**. This changes the
secret-free/file-read-only decision in accounts.md and PR #39 only if the
maintainer accepts it. The contributor needs the capabilities already running
in the fork: old accounts visible, editable through the web and separate AWS /
Alibaba access keys. Keep the upstream API, account model, aliases and access
tests rather than adding a second independent Accounts implementation.

## Canonical behavior

- Show file and UI accounts together in Settings > Cloud accounts.
- An admin can explicitly adopt a file account into UI management. Its provider
  and account ID remain immutable; inventory and history remain attached.
- An adopted UI row wins future file collisions. Retain disabled state and
  account configuration during reconciliation; do not turn UI accounts into file
  rows that the next collector disables when absent from accounts.yaml.
- Connection mode is runtime identity (default) or encrypted per-account keys.
  AWS supports an optional session token; Alibaba requires a complete key pair.
  Existing role ARN/external ID settings remain available with either mode.
- Saving does not scan or change cloud resources. Test access and collection use
  the same effective account credentials and read-only provider calls.

## Credentials and API

- Keys are write-only, represented with SecretStr and encrypted with the stable
  runtime Fernet key. Bind encrypted payloads to provider/account identity and
  retain the fork encryption format so existing ciphertext is readable.
- No keys in logs, API responses, browser storage, query/mutation caches or Git.
  Responses expose only credential mode and a boolean indicating stored keys.
- Omitted keys on edit retain existing ciphertext; replacement requires a full
  pair. Changing to runtime identity explicitly clears that account's keys.
- The form masks inputs and clears them on submission, error, cancellation,
  account/provider/mode changes and unmount.
- Full admin session and CSRF are required. Recheck admin authorization inside
  mutations and share the collection lock. Never change process-wide cloud
  environment variables for per-account credentials.
- Validate direct-key caller identity before collecting another account's data;
  retain upstream access-test timeout/retry limits and cloud-alias support.

## Compatibility and release

Use a new migration after 0005; never modify an applied 0004/0005. Recognize the
fork's actual schema instead of trusting its Alembic head. Preserve encrypted
keys, names, enabled flags, UI ownership, regions, roles, aliases and all referenced
inventory/history/users/MFA. Unknown or invalid configuration stops with a
sanitized error instead of discarding credentials or silently changing access.

Until this proposal is accepted and implemented, a database with stored keys must
not be cut over to the secret-free upstream model. The guarded reconciliation
PR stops such an upgrade before mutation. Backup/restore testing and a reviewed
previous-image recovery plan are required before shared deployment.

## Acceptance for the implementation PR

- Fresh-upstream and hybrid-fork upgrade tests; ciphertext byte-for-byte retained
  and decryptable with the original runtime key.
- AWS and Alibaba fake-provider tests cover separate account credentials,
  rotation, runtime mode, direct identity mismatch and optional roles.
- API tests cover admin/CSRF/authorization changes, validation, secret redaction,
  retained keys, adoption/file collisions, disabled rows and collection locking.
- Manual sync, scheduled CLI, aliases and access tests consume identical account
  credentials without stale client caches or cross-account leakage.
- Frontend tests cover old accounts, adoption/edit forms, masked inputs and secret
  clearing. Existing Search/Settings account views and inventory remain intact.
- Disposable staging upgrade preserves login, MFA, inventory and sync history.

## Maintainer decision required

Accept this behavior or retain the role-only upstream model. If role-only is
chosen, preserve the running fork separately and agree on explicit operator-led
credential conversion before migration; do not delete keys as an incidental step.
