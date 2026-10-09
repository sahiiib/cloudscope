# HTTP API

Base path `/api`. JSON only. All endpoints except `/api/auth/login`,
`/api/auth/mfa/verify-login` and `/healthz` require a session with
`mfa_passed = true`. Errors use FastAPI's `{"detail": ...}` shape.

OpenAPI is served at `/api/docs` (admin only in production).

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
| `q` | string | Free text. Matches name, instance ID, any IP, tag key or value. Case-insensitive substring (trigram). |
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

`GET /api/accounts` → `[{provider, account_id, name, enabled, last_success_at, instance_count}]`

## Sync

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/sync/runs?limit=20` | Recent runs with summary |
| GET | `/api/sync/runs/{id}` | Run plus per account/region results |
| POST | `/api/sync/runs` | Admin. Starts a manual run in a background thread; `409` if one is running |
