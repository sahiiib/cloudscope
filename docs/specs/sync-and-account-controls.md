# Per-account sync, stopping a sync, and the account dialog

Requested by Saheb on 2026-10-16. Covers T-076 and T-077. All cloud calls stay
read-only; all writes below need an admin full session and the CSRF header.

## Per-account sync (T-076)

`POST /api/sync/runs` accepts an optional body `{provider, account_id}`.

- With no body it behaves as today (every enabled account).
- With a body it collects only that account, using the runner's existing
  `account_id` filter. Unknown, deleted or disabled accounts return 404 / 409.
- It takes the same global collection lock, so only one run (scheduled, full
  manual or per-account) collects at a time; a busy lock returns 409.
- Migration (additive): `sync_runs.scope_provider` and
  `sync_runs.scope_account_id`, both nullable. Null means a full run.
  Run responses add `scope: null | {provider, account_id}`.
- A per-account run updates only that account's instances, load balancers and
  `last_success_at`; other accounts' rows are untouched.

UI: each row on the Accounts page gets a Sync icon button
(`aria-label="Sync <name>"`), disabled while any run is `running` or the
account is disabled. The Sync page shows the scope of each run ("All accounts"
or the account name and ID).

## Stopping a sync (T-076)

`POST /api/sync/runs/{id}/cancel` asks a running run to stop.

- Migration (additive): `sync_runs.cancel_requested_at` (nullable timestamptz)
  and a new terminal status `cancelled`.
- Returns 202 when the flag is set, 409 if the run is not `running`, 404 if
  unknown. Repeating it is harmless.
- The runner reads the flag from the database, so a run started by the CronJob
  pod can be stopped from the API pod. It checks before each account's region
  discovery and before each region scan starts; scans already in flight finish
  (no SDK call is interrupted). Pending scans are not started.
- The run then ends with status `cancelled`, `finished_at` set and the counts
  of what completed. Accounts whose regions were not all scanned do not get
  `last_success_at`, and missing-instance marking only applies to regions that
  were actually scanned (same rule as today's per-region results).
- Cancellation is logged as `event=sync_cancel_requested actor=<id> run_id=<id>`.

UI: the running run on the Sync page gets a Stop button with a confirmation;
after confirming it shows "Stopping…" until the run leaves `running`.

## Account dialog, excluded regions and pre-save test (T-077)

### Dialog

Add account and Edit account open in a modal dialog over the Accounts table,
not below it. The dialog has a title, traps focus, closes on Esc or Cancel,
asks before discarding unsaved changes, and returns focus to the button that
opened it. Validation, write-only key fields and version checks stay as in
[accounts.md](accounts.md) and [account-credentials.md](account-credentials.md).

### Excluded regions

- Migration (additive): `accounts.excluded_regions` JSONB list, default `[]`.
  Same item format as `regions`, unique, at most 64 entries.
- API: account responses return `excluded_regions`; create and patch accept it.
  `accounts.yaml` entries may set it too.
- The collector and the access test drop excluded regions after region
  discovery (or from an explicit `regions` list). If nothing remains, the
  account fails region discovery with `no regions left after exclusions`.
- Excluding a region marks that account/region's instances and load balancers
  missing on the next successful run of the account, as if the region were gone.

### Test before saving

`POST /api/accounts/test-connection` takes the same body as create (provider,
account_id, connection mode, role ARN/external ID and write-only keys) and runs
the existing access test without saving anything.

- Response: `{ok: true, regions: [<region ids>]}` or `{ok: false, error}` with
  the same sanitised errors and the 30 s deadline as the existing test.
- Keys sent here are used for this one test and dropped: never stored in the
  database, a Secret or logs. Audit log `event=account_test_connection actor=…
  provider=… account_id=… ok=…`.
- The existing `POST /api/accounts/{provider}/{account_id}/test` also returns
  `region_ids` with the discovered list.

UI: the Add and Edit dialogs have a Test connection button. On success they show
the discovered regions as a checklist so the admin can tick regions to exclude;
the choice is saved as `excluded_regions`.
