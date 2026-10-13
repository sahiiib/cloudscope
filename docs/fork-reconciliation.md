# Fork database reconciliation (T-064)

Migration 0006 handles the fork 0004/upstream 0005 collision without changing
applied migration files. A normal upstream schema needs no changes. A hybrid
without stored credentials gains the upstream columns/defaults/source check,
copies validated role/external-ID/region metadata, marks reconciled accounts as
file-managed and removes the empty legacy credential/configuration columns.
The next collection reconciles file rows with accounts.yaml; entries not in that
file are disabled and can be configured through the upstream account workflow.

**Stored credentials stop the upgrade before schema or data changes.** The
maintainer has selected the upstream role-only model. Removing fork-stored keys
is a separate, explicit operator action after a verified backup; it is not done
automatically by migration or by adding this document. See the conversion step
below. This task does not wait on the closed per-account-key proposal.

Unknown tables/columns stop reconciliation rather than guessing. Logs contain
counts only. Account identities, instances, sync history, users, sessions and
MFA remain intact. Runtime credentials and encryption keys are not changed.

## Rollout after review

1. Back up the DB, runtime encryption key and deployment values outside GitHub.
2. Restore into a separate disposable DB and verify the restore. Inspect actual
   schema and credential/configuration counts without printing values. Confirm
   all desired accounts are represented in the target accounts.yaml; reconciled
   file rows absent from it will be disabled by the next collect run.
3. On the disposable restore, perform the explicit clearing transaction below,
   migrate and configure role/base access. Verify login, MFA, Search, Accounts,
   "Test access" in Settings and collection. Verify the tested recovery procedure.
4. Review the recovery plan, provision read-only roles outside the application,
   and schedule shared cutover with the operator. Pause the old API/collector to
   prevent new writes during the conversion. Keep the runtime encryption key
   unchanged because it is also required for MFA and backed-up credentials.
5. Only after the verified backup and successful staging checks, the operator
   performs the same explicit clearing transaction on the shared DB, runs the
   reviewed migration and deploys the same tested upstream images. Configure a
   role_arn for affected accounts or use the base credentials; confirm with
   "Test access" in Settings before resuming collection. Do not stamp revisions
   to bypass the guard or mix an old fork application with the converted schema.

## Explicit operator conversion

This step removes key material from the live account rows. A verified backup and
reviewed role/base access plan are prerequisites. First run it on the disposable
restore; shared execution is a separate operator action, not an instruction for
an unattended migration hook. Connect to the intended database explicitly.

```sql
BEGIN;
UPDATE accounts
SET credentials_encrypted = NULL
WHERE credentials_encrypted IS NOT NULL;
```

Record the SQL client's `UPDATE <row count>` command result, never key values,
account IDs or `RETURNING *`. Roll back if the count differs from the reviewed
preflight count. If the count matches, commit the still-open transaction:

```sql
COMMIT;
```

Once committed, run `alembic upgrade head`. Migration logs
`event=reconcile_dropped_credentials count=0` after this step because no active
ciphertext remains; the clearing transaction's separate count is the audit
record of removed credentials. A missing legacy column also produces count 0
when legacy configuration columns are removed.

Downgrade 0006 does nothing: it cannot recreate lost legacy configuration.
Recovery uses a tested backup restore or a reviewed forward fix. Helm rollback
does not restore database data. No shared-environment migration is performed as
part of preparing this PR.
