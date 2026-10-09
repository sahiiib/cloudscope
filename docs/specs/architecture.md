# Architecture

## Components

| Component | Runs as | Responsibility |
| --- | --- | --- |
| `collector` | `cloudscope collect` (K8s CronJob, every 15 min) | Scan all accounts × regions, upsert instances, record sync runs |
| `api` | `cloudscope api` (K8s Deployment) | Auth, search, details, accounts, sync status, manual sync trigger |
| `web` | static files served by nginx (K8s Deployment) | React UI, talks only to `/api` |
| `postgres` | StatefulSet locally, RDS optional on EKS | Single source of truth |

The collector and the API share one Python package (`backend/cloudscope`) and
one container image; the command decides what runs.

## Stack

| Area | Choice |
| --- | --- |
| Language | Python 3.12 |
| Packaging | `uv` (`backend/pyproject.toml`) |
| Web framework | FastAPI, Pydantic v2 |
| DB access | SQLAlchemy 2.x (sync engine), Alembic migrations, psycopg 3 |
| AWS SDK | boto3 |
| Alibaba SDK | `alibabacloud_ecs20140526`, `alibabacloud_sts20150401`, `alibabacloud_vpc20160428` |
| Auth | `argon2-cffi` (passwords), `pyotp` (TOTP), `cryptography` Fernet (TOTP secret at rest) |
| CLI | Typer |
| Tests | pytest, `moto` for AWS, hand-written fakes for Alibaba |
| Lint / types | ruff, mypy (strict on `cloudscope/`) |
| Frontend | React 18, TypeScript, Vite, TanStack Query, TanStack Table, React Router |
| Frontend tests | Vitest + Testing Library |
| Packaging / deploy | Docker, Helm 3 |
| CI | GitHub Actions |

## Backend package layout

```
backend/
  pyproject.toml
  alembic.ini
  migrations/
  cloudscope/
    __init__.py
    cli.py              # typer app: api, collect, create-user, ...
    config.py           # settings from env (pydantic-settings) + accounts.yaml loader
    db/
      models.py         # SQLAlchemy models (see data-model.md)
      session.py
    collector/
      base.py           # Provider protocol, NormalizedInstance dataclass
      aws.py
      alibaba.py
      runner.py         # fan-out over accounts × regions, upsert, sync_runs
    auth/
      passwords.py
      totp.py
      sessions.py
      deps.py           # FastAPI dependencies: current_user, require_admin
    api/
      app.py            # FastAPI app factory
      routes/
        auth.py
        instances.py
        accounts.py
        sync.py
  tests/
```

## Configuration

Two sources:

1. **Environment variables** (12-factor, via `pydantic-settings`, prefix `CLOUDSCOPE_`):

| Variable | Purpose |
| --- | --- |
| `CLOUDSCOPE_DATABASE_URL` | `postgresql+psycopg://...` |
| `CLOUDSCOPE_API_HOST` | API bind address, default `127.0.0.1`; use `0.0.0.0` in containers |
| `CLOUDSCOPE_API_PORT` | API listen port, default `8000` |
| `CLOUDSCOPE_SECRET_KEY` | Fernet key for encrypting TOTP secrets |
| `CLOUDSCOPE_ACCOUNTS_FILE` | Path to accounts YAML (default `config/accounts.yaml`) |
| `CLOUDSCOPE_SESSION_TTL_HOURS` | Session lifetime, default 12 |
| `CLOUDSCOPE_COOKIE_SECURE` | `true` in k8s, `false` for local http |
| `CLOUDSCOPE_COLLECT_CONCURRENCY` | Parallel (account, region) scans, default 8 |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_PROFILE` | Base AWS credentials (local only; standard boto3 chain) |
| `ALIBABA_CLOUD_ACCESS_KEY_ID` / `ALIBABA_CLOUD_ACCESS_KEY_SECRET` | Base Alibaba credentials |

The API host and port are read directly from the process environment by Typer;
`cloudscope api --host ... --port ...` overrides them. Export these variables
or inject them through the container environment; the CLI does not load `.env`.

2. **Accounts file** (`config/accounts.yaml`, mounted from a ConfigMap; contains
   no secrets):

```yaml
accounts:
  - provider: aws
    account_id: "111111111111"
    name: prod-main
    # Optional. If omitted, base credentials are used directly (test mode).
    role_arn: arn:aws:iam::111111111111:role/cloudscope-readonly
    external_id: cloudscope            # optional
    regions: all                       # or a list: [eu-central-1, us-east-1]

  - provider: alibaba
    account_id: "1234567890123456"
    name: cn-prod
    role_arn: acs:ram::1234567890123456:role/cloudscope-readonly   # optional
    regions: [cn-hangzhou, cn-shanghai, me-east-1]
```

`regions: all` means: ask the provider for enabled regions at sync time.

## Key design decisions

- **Pull, not push.** The collector polls Describe APIs. No agents on instances,
  no event pipelines. 15 minutes is fresh enough for an inventory.
- **Normalized columns + raw JSON.** Fields used for listing, search and filters
  are columns. Everything else is kept in `raw` (provider payload) and
  `details` (normalized extras such as security groups). New detail fields need
  a UI change only, not a re-collect or a migration.
- **Never delete on sync.** Instances that disappear are marked
  `present = false` and keep their last data, so terminated instances remain
  searchable.
- **Read-only cloud access.** Only `Describe*` / `List*` permissions.
- **One account or region failing never fails the run.** Errors are stored per
  sync run and shown in the UI.
