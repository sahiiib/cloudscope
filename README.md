# cloudscope

A private web app that inventories compute instances across many cloud accounts
and regions, so you can search for an instance and see which account and region
it lives in, plus its full details.

Supported providers:

- **AWS** EC2 instances (about 12 accounts)
- **Alibaba Cloud** ECS instances (about 8 accounts)

## How it works

```
 ┌──────────────┐   AssumeRole / STS    ┌───────────────────────────┐
 │  collector   │ ────────────────────▶ │ AWS accounts × regions    │
 │ (CronJob,    │                       │ Alibaba accounts × regions│
 │  every 15m)  │ ◀──── Describe* ───── └───────────────────────────┘
 └──────┬───────┘
        │ upsert
        ▼
 ┌──────────────┐        ┌──────────────┐        ┌──────────────┐
 │  PostgreSQL  │ ◀───── │   API        │ ◀───── │  Web UI      │
 │              │        │  (FastAPI)   │        │  (React)     │
 └──────────────┘        └──────────────┘        └──────────────┘
```

- The **collector** reads every configured account and region with read-only
  credentials and writes a normalized record per instance (plus the raw API
  payload) into PostgreSQL.
- The **API** serves search, instance details, accounts and sync status, behind
  a username/password login with optional TOTP MFA (Google Authenticator).
- The **web UI** has a search page with filters and an instance details page.

The app is read-only towards the clouds. It never creates, changes or deletes
cloud resources.

## Repository layout

```
backend/            Python package `cloudscope` (API, collector, auth, DB)
frontend/           React + TypeScript web UI
deploy/helm/        Helm chart (local kubeadm cluster and EKS)
docs/               Roadmap, specs and the task list
AGENTS.md           Rules for coding agents (Codex, Claude) working in this repo
```

## Documentation

| Doc | What it covers |
| --- | --- |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Phases and milestones |
| [docs/TASKS.md](docs/TASKS.md) | Task list with owners and acceptance criteria |
| [docs/specs/architecture.md](docs/specs/architecture.md) | Components, stack, config |
| [docs/specs/data-model.md](docs/specs/data-model.md) | Database tables and normalized fields |
| [docs/specs/collector.md](docs/specs/collector.md) | How AWS and Alibaba are scanned |
| [docs/specs/api.md](docs/specs/api.md) | HTTP API |
| [docs/specs/auth.md](docs/specs/auth.md) | Login, sessions, TOTP MFA |
| [docs/specs/ui.md](docs/specs/ui.md) | Pages and fields shown |
| [docs/specs/deployment.md](docs/specs/deployment.md) | Docker, Helm, local cluster, EKS |
| [docs/specs/cloud-access.md](docs/specs/cloud-access.md) | IAM / RAM setup in each account |

## Open in VS Code

```bash
gh repo clone sahiiib/cloudscope
code cloudscope/cloudscope.code-workspace
```

Accept "Install recommended extensions" when VS Code asks. The workspace
includes GitHub Pull Requests, Python/ruff/mypy, ESLint/Prettier, YAML,
Kubernetes, Docker, Codex and Claude Code.

## Quick start (local development)

The backend scaffold runs with Python 3.12 and uv:

```bash
make setup
make lint
make test
cd backend && uv run cloudscope api
```

The API listens on `http://localhost:8000`. `/healthz` and `/readyz` return
`{"status":"ok"}`; readiness does not check a database until T-005.
Use `uv run cloudscope api --host 0.0.0.0 --port 9000` to change the bind address,
or export `CLOUDSCOPE_API_HOST` and `CLOUDSCOPE_API_PORT`. CLI options take
precedence over environment variables; defaults remain `127.0.0.1:8000`.

Runtime configuration is available through `cloudscope.config.Settings`.
Export `CLOUDSCOPE_DATABASE_URL` and a valid `CLOUDSCOPE_SECRET_KEY` before
instantiating settings; `.env` is not loaded automatically. Secure cookies
default to enabled; use `CLOUDSCOPE_COOKIE_SECURE=false` for local HTTP.
From `backend/`, set `CLOUDSCOPE_ACCOUNTS_FILE=../config/accounts.yaml` (relative
paths use the working directory). `load_accounts(settings.accounts_file)`
loads the validated account list. Account IDs must be quoted YAML strings;
invalid entries and duplicate provider/account pairs report descriptive errors.
See [configuration](docs/specs/architecture.md#configuration) for all defaults.

> The full application setup below is not runnable yet. These commands become valid as tasks in
> [docs/TASKS.md](docs/TASKS.md) land.

```bash
cp .env.example .env              # fill in DB URL and test cloud keys (never commit .env)
cp config/accounts.example.yaml config/accounts.yaml

docker compose up -d postgres
cd backend && uv sync && uv run alembic upgrade head
uv run cloudscope create-user admin --admin
uv run cloudscope collect          # one sync run
uv run cloudscope api              # http://localhost:8000

cd ../frontend && npm install && npm run dev   # http://localhost:5173
```

## Security

- Never commit credentials. `.env`, `config/accounts.yaml` and anything under
  `secrets/` are git-ignored.
- Cloud credentials must be read-only. See
  [docs/specs/cloud-access.md](docs/specs/cloud-access.md).
