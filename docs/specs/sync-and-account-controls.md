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

## Region picker in the Edit dialog (T-079)

Requested by Saheb on 2026-10-16 after testing T-077. Replaces the "re-enter
dedicated keys to test while editing" decision and changes how the region
checklist is shown. Saved data stays the same: `excluded_regions`.

### Test while editing uses the saved keys

- `POST /api/accounts/{provider}/{account_id}/test-connection` takes the same
  body as `POST /api/accounts/test-connection` (provider and account ID come
  from the path and must match the body if present).
- If the body has no `credentials` and the account is saved as `dedicated`,
  the server loads that account's own saved keys from its Secret, the same way
  the collector does. Keys never go back to the browser and are not logged.
- Saved keys are only used for the same provider and account ID. Changing
  connection mode to dedicated without saved keys still requires keys.
- New keys typed in the form still override the saved ones for that test.
- Errors, the 30 s deadline and the audit log `event=account_test_connection`
  are the same as the unsaved test.
- The Edit dialog uses this endpoint; Add keeps using the unsaved one.

### Region list with counts

`GET /api/accounts/{provider}/{account_id}/regions` (admin) returns
`{regions: [{region, instances, load_balancers, excluded}]}`, sorted by region.

- The list is the union of: regions in the account's most recent run that
  scanned it, regions with present instances or load balancers, and
  `excluded_regions`.
- `instances` and `load_balancers` count present rows in that region (0 for
  an excluded region whose rows were retired).
- No cloud calls; reads only the database. Empty list for an account that
  never synced.

### Dialog

- Under the Regions text box there is a **Select regions** button. It replaces
  the separate Test connection button: it runs the connection test and, on
  success, shows "Connection OK" and refreshes the region list with any newly
  discovered regions (counts 0 for new ones).
- When editing an account that has synced before, the region list loads from
  `GET …/regions` as soon as the dialog opens, without a test.
- The checklist means **scan this region**: every region is ticked except the
  ones in `excluded_regions`. Unticking a region excludes it. Saving sends the
  unticked regions as `excluded_regions`.
- Each row shows the counts, for example `eu-central-1 · 12 instances · 3 load
  balancers`.
- Unticking every region shows "Keep at least one region" and blocks saving.
