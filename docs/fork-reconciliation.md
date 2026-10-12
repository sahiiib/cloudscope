# Fork database reconciliation (T-064)

Migration 0006 handles the fork 0004/upstream 0005 collision without changing
applied migration files. A normal upstream schema needs no changes. A hybrid
without stored credentials gains the upstream columns/defaults/source check,
copies validated role/external-ID/region metadata, marks reconciled accounts as
file-managed and removes the empty legacy credential/configuration columns.
The next collection reconciles file rows with accounts.yaml; entries not in that
file are disabled and can be configured through the upstream account workflow.

**Stored credentials stop the upgrade before schema or data changes.** This is
an intentional deviation from the unconditional deletion in the plan merged in
PR #39: the fork user requested retaining per-account keys. The account-access
design must be resolved before upgrading a database with keys. There is no
discard flag and this PR must not be used to cut over that database prematurely.

Unknown tables/columns stop reconciliation rather than guessing. Logs contain
counts only. Account identities, instances, sync history, users, sessions and
MFA remain intact. Runtime credentials and encryption keys are not changed.

## Rollout after review

1. Back up the DB, runtime encryption key and deployment values outside GitHub.
2. Restore into a separate disposable DB and verify the restore. Inspect actual
   schema and credential/configuration counts without printing values.
3. Run the reviewed migration on the restore and check schema, retained data,
   login, Search, Accounts, access checks and collection. A stored-key refusal
   means stop and resolve the design; do not delete keys or stamp the DB to bypass it.
4. Only after review, successful staging checks and an agreed recovery plan,
   apply the same upstream images and migration through the designated operator.

Downgrade 0006 does nothing: it cannot recreate lost legacy configuration.
Recovery uses a tested backup restore or a reviewed forward fix. Helm rollback
does not restore database data. No shared-environment migration is performed as
part of preparing this PR.
