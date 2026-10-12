# Cloud accounts managed in the UI

Admins can add and edit AWS and Alibaba accounts from the web UI, in addition
to `accounts.yaml`. Accounts never hold secrets: only IDs, names, an optional
role to assume and regions. Base credentials stay in the Kubernetes Secret
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
- File accounts are read-only in the UI and labelled "Managed by accounts.yaml".
- After the file sync, the collector scans every **enabled** row from the
  database, whatever its source.
- Accounts are never deleted (instances reference them). Disabling an account
  stops scanning it; its instances keep their last observed data, as for an
  account removed from the file today.
- A missing accounts file is no longer an error once UI accounts exist: the run
  treats a missing file as an empty list of file accounts. An invalid file still
  fails the run as today.

## Account fields and validation

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
writes inventory. Cloud SDK code for it lives in `cloudscope/collector/`.

## Audit logging

Every create, update, enable/disable and access test is logged as
`event=account_<action> actor=<user id> provider=… account_id=…`, plus
`changed=<field names>` for updates. Values of `role_arn` and `external_id` are
never logged.
