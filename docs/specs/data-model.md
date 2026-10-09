# Data model

PostgreSQL 16. All timestamps are `timestamptz` in UTC. Migrations live in
`backend/migrations` (Alembic). Requires the `pg_trgm` extension.

## `accounts`

Synced from `accounts.yaml` at the start of every collect run.

| Column | Type | Notes |
| --- | --- | --- |
| `provider` | text | `aws` \| `alibaba` |
| `account_id` | text | |
| `name` | text | Friendly name from config |
| `enabled` | bool | `false` when removed from config |
| `last_success_at` | timestamptz null | Last fully successful scan of this account |

Primary key: `(provider, account_id)`.

## `instances`

One row per instance ever seen.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | bigserial | Surrogate PK |
| `provider` | text | `aws` \| `alibaba` |
| `account_id` | text | FK → accounts |
| `region` | text | e.g. `eu-central-1`, `cn-hangzhou` |
| `zone` | text null | AZ / zone id |
| `instance_id` | text | `i-...` / `i-...` |
| `name` | text null | AWS `Name` tag; Alibaba `InstanceName` |
| `state` | text | Normalized, see below |
| `provider_state` | text | Raw state string from the provider |
| `instance_type` | text | |
| `private_ips` | text[] | All private IPv4 on all interfaces |
| `public_ips` | text[] | Public + Elastic / EIP addresses |
| `tags` | jsonb | `{"key": "value"}` |
| `launch_time` | timestamptz null | AWS `LaunchTime`; Alibaba `CreationTime` |
| `vpc_id` | text null | |
| `subnet_id` | text null | AWS subnet / Alibaba vSwitch |
| `key_name` | text null | AWS `KeyName`; Alibaba `KeyPairName` |
| `image_id` | text null | |
| `platform` | text null | `linux` / `windows` / provider value |
| `details` | jsonb | Normalized extras, see below |
| `raw` | jsonb | Unmodified provider instance payload |
| `first_seen` | timestamptz | |
| `last_observed` | timestamptz | Updated on every scan that sees it |
| `present` | bool | `false` once a successful scan of its account+region no longer sees it |
| `search_text` | text | Generated: name, instance_id, ips, tag keys/values, lowercased |

Unique: `(provider, account_id, region, instance_id)`.

Indexes:
- GIN trigram on `search_text`
- btree on `provider`, `account_id`, `region`, `state`, `present`
- GIN on `tags`

### Normalized `state`

| Normalized | AWS | Alibaba |
| --- | --- | --- |
| `pending` | pending | Pending, Starting |
| `running` | running | Running |
| `stopping` | stopping, shutting-down | Stopping |
| `stopped` | stopped | Stopped |
| `terminated` | terminated | (instance gone / Released) |
| `unknown` | anything else | anything else |

### `details` JSON shape

Same shape for both providers. Missing parts are `null` or `[]`.

```json
{
  "security_groups": [
    {
      "id": "sg-123",
      "name": "web",
      "description": "...",
      "inbound": [{"protocol": "tcp", "port_range": "443", "source": "0.0.0.0/0", "description": ""}],
      "outbound": [{"protocol": "-1", "port_range": "all", "destination": "0.0.0.0/0", "description": ""}]
    }
  ],
  "vpc": {"id": "vpc-1", "name": "main", "cidr": "10.0.0.0/16"},
  "subnet": {"id": "subnet-1", "name": "private-a", "cidr": "10.0.1.0/24"},
  "network_interfaces": [
    {"id": "eni-1", "private_ips": ["10.0.1.5"], "public_ip": null, "mac": "...", "security_group_ids": ["sg-123"]}
  ],
  "key_pair": {"name": "ops-key"},
  "iam_role": "arn:aws:iam::...:instance-profile/...",
  "image": {"id": "ami-...", "name": null},
  "cpu": 2,
  "memory_mib": 4096,
  "monitoring": "disabled"
}
```

The detail field list will grow. New fields go into `details` (normalized) and
the UI; `raw` already has the provider data, so a re-collect is only needed if
an extra API call is required.

## `sync_runs`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | bigserial | |
| `started_at` / `finished_at` | timestamptz | |
| `trigger` | text | `schedule` \| `manual` |
| `status` | text | `running` \| `success` \| `partial` \| `failed` |
| `instances_seen` | int | |

## `sync_results`

One row per (run, account, region).

| Column | Type | Notes |
| --- | --- | --- |
| `run_id` | bigint | FK → sync_runs |
| `provider`, `account_id`, `region` | text | |
| `status` | text | `success` \| `error` |
| `instances_seen` | int | |
| `error` | text null | Short message, no credentials |
| `duration_ms` | int | |

## `users`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | bigserial | |
| `username` | text unique | |
| `password_hash` | text | argon2id |
| `is_admin` | bool | |
| `is_active` | bool | |
| `totp_secret_enc` | text null | Fernet-encrypted base32 secret |
| `mfa_enabled` | bool | |
| `failed_logins` | int | |
| `locked_until` | timestamptz null | |
| `created_at`, `last_login_at` | timestamptz | |

## `sessions`

| Column | Type | Notes |
| --- | --- | --- |
| `id_hash` | text PK | SHA-256 of the random session token (token itself only in cookie) |
| `user_id` | bigint | FK → users |
| `mfa_passed` | bool | `false` between password step and TOTP step |
| `created_at`, `expires_at`, `last_seen_at` | timestamptz | |
| `ip`, `user_agent` | text | |
