# Cloud accounts managed in the UI

Admins can add and edit AWS and Alibaba accounts from the web UI, in addition
to `accounts.yaml`. Accounts never hold secrets: only IDs, names, an optional
role to assume and regions. The optional Secret-backed extension is defined in
[account-credentials.md](account-credentials.md); the database holds references,
never keys. Base credentials stay in the Kubernetes Secret
(test keys) or workload identity (EKS); see [cloud-access.md](cloud-access.md).

## Two sources, one table

Every account is a row in `accounts` with a `source`:

| `source` | Created by | Edited by | Disabled when |
| --- | --- | --- | --- |
| `file` | `accounts.yaml` (chart `accounts` value) | the file only | removed from the file |
| `ui` | an admin, in Settings → Cloud accounts | admins in the UI | an admin disables it |

- At the start of every collect run (scheduled, CLI or "Sync now") the file is
  synced as today, but only rows with `source = file` are inserted, updated or
  disabled. Rows with `source = ui` are never touched by the file.
- If the file lists a (provider, account_id) that already exists as a `ui` row,
  the UI row wins: the file entry is skipped and logged as
  `event=account_file_conflict provider=… account_id=…`. The run continues.
- An admin cannot create a UI account whose (provider, account_id) already
  exists in either source (409).
- File accounts are read-only until explicit **Manage in web** adoption, and labelled "Managed by accounts.yaml".
- After the file sync, the collector scans every **enabled** row from the
  database, whatever its source.
- Admins can delete an account from the console after explicit confirmation.
  Deletion keeps a disabled UI tombstone with saved inventory/history, while hiding
  the account, its instances and load balancers. File sync cannot recreate it.
  Re-adding the same provider/account ID restores it with the supplied connection
  settings. This never deletes cloud resources or credential Secret versions.
  Disabling alone still retains visible last-observed inventory.
- A missing accounts file is no longer an error once UI accounts exist: the run
  treats a missing file as an empty list of file accounts. An invalid file still
  fails the run as today.

## Account fields and validation

### Key-first creation and deletion (T-072)

When dedicated credentials are enabled, Add account starts with Access Key ID
and Secret Access Key visible for both AWS and Alibaba. Runtime and Assume Role
remain selectable. Editing retains the current connection method.

`DELETE /api/accounts/{provider}/{account_id}` requires an authenticated admin,
CSRF and `{confirmed: true, expected_version: <current>}`. Stale edits or active
collection return 409; missing/deleted accounts return 404. The global collection
lock serializes deletion with scans and edits. It sets deleted=true, enabled=false,
source=ui and increments the version. Search/facets/details, LB inventory and scan
status exclude deleted accounts. Re-adding restores the original row/history.
Migration 0009 is additive and refuses downgrade while deleted rows remain.

Same rules as `AccountConfig` in [architecture.md](architecture.md#configuration),
plus provider-specific formats, applied to API input:

| Field | Rule |
| --- | --- |
| `provider` | `aws` or `alibaba`; immutable after create |
| `account_id` | AWS: exactly 12 digits. Alibaba: exactly 16 digits. Immutable after create |
| `name` | 1–64 characters, no leading/trailing whitespace, no control characters |
| `role_arn` | Optional. AWS: `arn:aws:iam::<account_id>:role/<name>`; Alibaba: `acs:ram::<account_id>:role/<name>`. The ID in the ARN must equal `account_id` |
| `external_id` | Optional, AWS only, 2–1224 characters of `[\w+=,.@:/-]` |
| `regions` | `"all"` or a non-empty list of unique region IDs matching `^[a-z0-9-]{2,32}$` |
| `enabled` | Boolean, default `true` |

Unknown fields are rejected (422). Errors name the field, never echo values.

## Access test

`POST /api/accounts/{provider}/{account_id}/test` lets an admin check an
account before relying on it. It runs, with the same credentials the collector
would use:

1. If `role_arn` is set: assume the role (AWS `sts:AssumeRole` with the
   external ID; Alibaba STS `AssumeRole`).
2. List the account's regions (`ec2:DescribeRegions` / ECS `DescribeRegions`).

Both are read-only calls already allowed by the roles in cloud-access.md. The
result is `{"ok": true, "regions": <count>}` or
`{"ok": false, "error": "<phase>: <SDK error code or exception class>"}`, with
the same sanitizing as sync errors. The call times out after 30 s and never
writes inventory. Access-test SDK clients use a 5 s connect timeout, 10 s read
timeout and at most two attempts per operation (collector scan retries stay
unchanged). The HTTP deadline remains 30 s; an in-flight SDK attempt can finish
in its worker after the deadline. AssumeRole errors are labelled
`Assume role failed: <code>`; region discovery errors are labelled
`Region discovery failed: <code>`. Cloud SDK code for it lives in `cloudscope/collector/`.

## Audit logging

Every create, update, enable/disable and access test is logged as
`event=account_<action> actor=<user id> provider=… account_id=…`, plus
`changed=<field names>` for updates. Values of `role_arn` and `external_id` are
never logged. Account IDs are consistently unquoted; unexpected characters in
legacy file IDs are escaped to prevent log injection.

## Cloud account alias

Besides the name from the file or the UI, each account shows the name it has
in the cloud, so a wrong name or ID is easy to spot.

- AWS: the account alias from `iam:ListAccountAliases` (first alias, or none).
- Alibaba: the account alias from RAM `GetAccountAlias`.

The collector reads it once per account per collect run, with the same
credentials as the scan, before scanning regions. It is stored in
`accounts.cloud_alias` with `cloud_alias_checked_at`. If the call fails
(for example `AccessDenied` because a role lacks the new permission), the old
value is kept, the error code is logged as
`event=account_alias_failed provider=… account_id=… error=<code>`, and the
scan continues; it never makes a region scan fail. An account with no alias
stores null.

Both calls are read-only. They need one extra permission in the read-only
roles (`iam:ListAccountAliases`, `ram:GetAccountAlias`); see
[cloud-access.md](cloud-access.md).

## Dialog and region exclusions (T-077)

Add/Edit opens an accessible modal over the Accounts page. Escape or Cancel asks
before discarding edits, keyboard focus stays inside, and closing restores focus
to the opener. Existing version checks and write-only credential fields remain.

`excluded_regions` is a list of at most 64 unique region IDs, default `[]`, for
both UI and file accounts. The Excluded regions section is always visible; before a
successful test it tells the admin to click Test connection. A connection preview shows effective discovered regions
as a checklist; checked entries are saved as exclusions. Existing exclusions stay
visible so they can be unchecked. Changing connection settings invalidates the
preview, except retyping cleared key inputs, which preserves the region checklist. If all regions are excluded, collection/test fails explicitly.

Test connection validates current unsaved settings without persistence. Dedicated
keys are cleared from the inputs after the check and must be re-entered to save;
editing with saved dedicated keys also requires a supplied pair for an unsaved
preview. Test access on the table remains available for testing the saved keys.
No keys enter query/mutation caches, browser storage, database, Secret or logs.
