# HTTP API

Base path `/api`. JSON only. All endpoints except `/api/auth/login`,
`/api/auth/mfa/verify-login`, `/healthz` and `/readyz` require a session with
`mfa_passed = true`. Logout also accepts an unexpired session awaiting MFA. Errors use FastAPI's `{"detail": ...}` shape.

OpenAPI UI is served at `/api/docs`, with its schema at `/api/openapi.json`
(both admin only).

## Health

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/healthz` | Liveness, no DB |
| GET | `/readyz` | Checks DB connection |

## Auth

See [auth.md](auth.md) for the flow.

| Method | Path | Body | Result |
| --- | --- | --- | --- |
| POST | `/api/auth/login` | `{username, password}` | `200 {mfa_required: bool}` + session cookie |
| POST | `/api/auth/mfa/verify-login` | `{code}` | `200` marks session `mfa_passed` |
| POST | `/api/auth/logout` | | `204` |
| GET | `/api/auth/me` | | `{id, username, is_admin, mfa_enabled}` |
| POST | `/api/auth/mfa/setup` | | `{otpauth_uri, qr_svg}` (secret stored, not yet enabled) |
| POST | `/api/auth/mfa/enable` | `{code}` | `204` |
| POST | `/api/auth/mfa/disable` | `{password, code}` | `204` |
| POST | `/api/auth/password` | `{current_password, new_password}` | `204` |

## Users (admin)

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/users` | List |
| POST | `/api/users` | `{username, password, is_admin}` |
| PATCH | `/api/users/{id}` | `{is_active?, is_admin?, password?}` |
| POST | `/api/users/{id}/reset-mfa` | Disables MFA for that user |

## Instances

### `GET /api/instances`

Query parameters:

| Param | Type | Notes |
| --- | --- | --- |
| `q` | string | Free text. Matches name, instance ID, any IP, tag key or value, account name, account alias or account ID. Case-insensitive substring (trigram). |
| `provider` | repeatable | `aws`, `alibaba` |
| `account_id` | repeatable | |
| `region` | repeatable | |
| `state` | repeatable | Normalized state |
| `tag` | repeatable | `key=value` or `key` |
| `include_missing` | bool | Default `false` (hide `present = false`) |
| `sort` | string | `name`, `launch_time`, `last_observed`, `region`, `account`; prefix `-` for desc. Default `name` |
| `page` | int | 1-based, default 1 |
| `page_size` | int | Default 50, max 500 |

Response:

```json
{
  "items": [
    {
      "provider": "aws",
      "account_id": "111111111111",
      "account_name": "prod-main",
      "account_alias": "example-production",
      "region": "eu-central-1",
      "instance_id": "i-0abc",
      "name": "web-1",
      "state": "running",
      "instance_type": "t3.medium",
      "private_ips": ["10.0.1.5"],
      "public_ips": ["3.120.1.2"],
      "tags": {"env": "prod"},
      "launch_time": "2026-01-02T10:00:00Z",
      "last_observed": "2026-10-09T11:00:00Z",
      "present": true
    }
  ],
  "total": 1234,
  "page": 1,
  "page_size": 50
}
```

### `GET /api/instances/{provider}/{account_id}/{region}/{instance_id}`

Returns the list item fields plus `zone`, `vpc_id`, `subnet_id`, `key_name`,
`image_id`, `platform`, `provider_state`, `first_seen`, `details` and `raw`.

### `GET /api/instances/facets`

Distinct values with counts for filters, respecting the other filters:
`{providers: [{value, count}], accounts: [...], regions: [...], states: [...]}`.

## Accounts

`GET /api/accounts` → `[{provider, account_id, name, enabled, last_success_at, instance_count, source, role_arn, external_id, regions, cloud_alias}]`

Instance list items and the instance detail also carry `account_alias` (the
account's `cloud_alias`, or null).

Admin only, full session and CSRF header (rules in [accounts.md](accounts.md)):

| Method | Path | Notes |
| --- | --- | --- |
| POST | `/api/accounts` | Create a `ui` account. Body `{provider, account_id, name, role_arn?, external_id?, regions, enabled?}`. 201 with the account; 409 if it exists; 422 on validation |
| PATCH | `/api/accounts/{provider}/{account_id}` | Change `name`, `role_arn`, `external_id`, `regions`, `enabled` of a `ui` account. Omitted fields unchanged; explicit null clears the optional ones. 409 for `file` accounts; 404 unknown |
| POST | `/api/accounts/{provider}/{account_id}/test` | Read-only access test, `200 {ok, regions}` or `200 {ok: false, error}`; 404 unknown |

There is no DELETE; disable instead.

## Sync

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/sync/runs?limit=20` | Recent runs with summary |
| GET | `/api/sync/runs/{id}` | Run plus per account/region results |
| POST | `/api/sync/runs` | Admin. Starts a manual run in a background thread; `409` if one is running |

### Inventory and sync query semantics

Repeated values within one filter are ORed; different filters and repeated tags
are ANDed. Free text treats `%` and `_` literally. Facets omit their own dimension
while retaining every other filter (including tags/search/missing). Account facet
values are account IDs; accounts with the same ID across providers share a bucket.
Account name/alias/ID matching joins the current account row, so renames take
effect without recollecting instances. List totals and facets use the same search
conditions. Sorting uses nulls last and a stable instance-ID database tie-breaker. Account
sorting uses account name. Account counts include present instances only; disabled
and empty accounts remain listed. Detail lookup also allows missing instances.

Sync history defaults to 20 runs, with `limit` between 1 and 500. Run detail adds
`results` containing provider, account_id, region, status, instances_seen, error,
and duration_ms. Manual sync returns `202 {"status": "accepted"}`; clients poll
history for progress. It shares the CLI's database advisory lock and returns 409
while either caller is collecting. Invalid collection configuration returns a
sanitized 503. API shutdown waits for its collection thread to finish.
### Admin user management semantics

User responses contain `id`, `username`, `is_admin`, `is_active`, `mfa_enabled`,
`created_at`, and `last_login_at`; hashes, encrypted secrets and lockout state are
never returned. Create returns 201 (409 for an existing username); usernames must
be nonblank, at most 256 characters, without surrounding whitespace. Passwords
must be at least 12 characters. PATCH returns the updated user; omitted fields
remain unchanged, explicit nulls and unknown fields are rejected. Unknown IDs
return 404. MFA reset returns 204.

All mutations require an admin full session and the CSRF header. Password or
privilege/activity changes revoke all of the target's sessions. Password reset
also clears password lockout counters. MFA reset clears enrollment and replay
state and revokes both full and half sessions. Self changes clear the cookie.
Removing the last active administrator returns 409; admin mutations serialize
this check and recheck the actor's authorization inside the transaction.

## Load balancer endpoints (T-069)

See [load-balancers.md](load-balancers.md) for the additive schema, read-only
operations, per-family failure behavior, API and opt-in rollout.

## Secret-backed account connections (T-071)

See [account-credentials.md](account-credentials.md) for the reviewed extension.
Account responses additionally return connection_mode, credentials_configured and
configuration_version, never keys or Secret references. Admin GET
/api/accounts/capabilities returns dedicated_credentials. Create/patch accept
connection_mode and write-only credentials (access_key_id, secret_access_key,
AWS-only optional session_token). Connection edits require expected_version;
stale edits or a running collector return 409. POST
/api/accounts/{provider}/{account_id}/adopt requires confirmed=true and
expected_version, and preserves existing data while making the UI authoritative.
All writes require full admin session and CSRF. Failed access validation returns
sanitized 422; unavailable Secret storage returns 503 without changing the account.

### Scoped collection and cancellation (T-076)

`POST /api/sync/runs` optionally accepts `{ "provider": "aws", "account_id": "111111111111" }`.
Omitting the body starts a full run. A missing/deleted account returns 404;
a disabled account or occupied global collection lock returns 409. Both scoped
and full runs return 202. Admin full session and CSRF are required.

Run list/detail responses include `scope: null | {provider, account_id}` and
`cancel_requested_at: null | <timestamp>`. Full runs have null scope. CLI
`--account` may select the ID across providers, represented by a null scope provider.

`POST /api/sync/runs/{id}/cancel` requires admin and CSRF. It returns 202 for a
running run (including repeated requests), 404 for an unknown run, or 409 for
a terminal run. The database flag also reaches scheduled collectors. In-flight
scans finish; pending account discovery and region scans stop. The terminal
status is `cancelled`, with counts for completed scans and a finish timestamp.
Unscanned regions retain their inventory; partially scanned accounts do not
advance `last_success_at`.
