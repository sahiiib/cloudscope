# Tasks

Rules for working on tasks are in [AGENTS.md](../AGENTS.md).

**Owner**: `codex` (implemented by Codex, reviewed by Claude), `claude`
(implemented by Claude), `human` (Saheb; needs cloud console access).
**Status**: `todo` → `in-progress` → `review` → `done` (or `blocked`).

A task can start when all its dependencies are `done`.

## Overview

| ID | Title | Owner | Depends on | Status |
| --- | --- | --- | --- | --- |
| T-001 | Repo skeleton, Makefile, .gitignore, CI | claude | – | done |
| T-002 | Backend project scaffold | codex | T-001 | done |
| T-003 | Frontend project scaffold | codex | T-001 | done |
| T-004 | Local Postgres via docker compose | codex | T-002 | done |
| T-005 | DB models and first migration | codex | T-004 | done |
| T-006 | Settings and accounts.yaml loader | codex | T-002 | done |
| T-010 | AWS EC2 provider | codex | T-005, T-006 | done |
| T-011 | Alibaba ECS provider | codex | T-005, T-006 | done |
| T-012 | Sync runner | codex | T-010 | done |
| T-013 | `cloudscope collect` CLI | codex | T-012 | todo |
| T-014 | First real sync with test keys | human + claude | T-013, T-011 | todo |
| T-020 | Users, passwords, `create-user` CLI | codex | T-005 | done |
| T-021 | Sessions and login API | codex | T-020 | done |
| T-022 | TOTP MFA | codex | T-021 | done |
| T-023 | Instances, accounts, sync API | codex | T-021, T-012 | todo |
| T-024 | Admin users API | codex | T-022 | todo |
| T-030 | UI: app shell, login, MFA step | codex | T-003, T-022 | todo |
| T-031 | UI: search page | codex | T-030, T-023 | todo |
| T-032 | UI: instance details page | codex | T-031 | todo |
| T-033 | UI: sync status page | codex | T-030, T-023 | todo |
| T-034 | UI: settings (password, MFA, users) | codex | T-030, T-024 | todo |
| T-040 | Dockerfiles and image build in CI | codex | T-013, T-003 | todo |
| T-041 | Helm chart | codex | T-040 | todo |
| T-042 | Local cluster install guide and values | claude | T-041 | todo |
| T-043 | Deploy to local kubeadm cluster | human + claude | T-042 | todo |
| T-050 | AWS read-only role StackSet + hub role templates | codex | T-010 | todo |
| T-051 | Alibaba RAM role Terraform | codex | T-011 | todo |
| T-052 | Roll out roles in all accounts | human | T-050, T-051 | todo |
| T-053 | EKS values: Pod Identity, external secret, RDS option | codex | T-041, T-050 | todo |

---

## Phase 0: Foundation

### T-001: Repo skeleton, Makefile, .gitignore, CI
Owner: claude · Specs: [architecture](specs/architecture.md)

- Create `backend/`, `frontend/`, `deploy/`, `config/` folders.
- `.gitignore` covering `.env`, `config/accounts.yaml`, `secrets/`, `*.pem`,
  `*.key`, Python and Node build output.
- `.env.example`, `config/accounts.example.yaml` (placeholder IDs only).
- Root `Makefile` with `setup`, `lint`, `test`, `dev-db`, `migrate` that
  delegate to backend/frontend.
- GitHub Actions: `ci.yml` running lint + tests for backend and frontend;
  `gitleaks` secret scan.

Acceptance: CI runs on PRs; gitleaks job fails if a fake AWS key is committed.

### T-002: Backend project scaffold
Owner: codex · Specs: [architecture](specs/architecture.md)

- `backend/pyproject.toml` with uv, Python 3.12, deps from the stack table.
- Package layout exactly as in architecture.md (empty modules allowed).
- Typer CLI `cloudscope` with `api` command starting uvicorn on the FastAPI app.
- FastAPI app factory with `/healthz` and `/readyz` (readyz may return 200
  without DB until T-005).
- ruff + mypy strict config; one pytest test hitting `/healthz`.

Acceptance: `make lint` and `make test` pass; `uv run cloudscope api` serves `/healthz`.

### T-003: Frontend project scaffold
Owner: codex · Specs: [ui](specs/ui.md)

- Vite + React 18 + TypeScript strict, React Router, TanStack Query.
- ESLint + `tsc --noEmit`, Vitest + Testing Library with one smoke test.
- Dev server proxies `/api` to `http://localhost:8000`.
- `src/api/client.ts`: fetch wrapper that sends `X-Requested-With: cloudscope`,
  `credentials: "same-origin"`, and redirects to `/login` on 401.

Acceptance: `npm run lint`, `npm test`, `npm run build` pass.

### T-004: Local Postgres via docker compose
Owner: codex · Specs: [architecture](specs/architecture.md)

- `docker-compose.yml` with `postgres:16`, a named volume, and healthcheck.
- `make dev-db` starts it; `.env.example` has the matching `DATABASE_URL`.
- pytest fixture that creates a throwaway database per test session
  (use the compose DB in local dev, a service container in CI).

Acceptance: DB tests run locally and in CI.

### T-005: DB models and first migration
Owner: codex · Specs: [data-model](specs/data-model.md)

- SQLAlchemy models for all tables in data-model.md.
- Alembic setup and initial migration including `pg_trgm`, all indexes, and
  `search_text` as a generated column (or maintained by the upsert, document
  which).
- `make migrate` applies it.

Acceptance: migration up/down works on an empty DB; a test inserts and reads
each model.

### T-006: Settings and accounts.yaml loader
Owner: codex · Specs: [architecture](specs/architecture.md#configuration)

- `pydantic-settings` class for all `CLOUDSCOPE_*` variables.
- Pydantic model for `accounts.yaml`; validation errors name the bad entry.
- `regions` accepts `all` or a non-empty list.

Acceptance: tests for valid file, unknown provider, duplicate account, empty regions.

## Phase 1: Collector

### T-010: AWS EC2 provider
Owner: codex · Specs: [collector](specs/collector.md#aws), [data-model](specs/data-model.md)

- `collector/aws.py` implementing the `Provider` protocol.
- AssumeRole with optional external ID and per-account credential caching;
  direct mode when `role_arn` is absent.
- Fill all `instances` columns and the full `details` shape (security groups
  with rules, VPC, subnet, ENIs, key pair, IAM profile, image, CPU).
- State mapping as in data-model.md.

Acceptance: moto tests cover two regions, multiple ENIs, SG rules, Name tag
missing, assumed-role account, and pagination (>1000 instances not required;
use small page size).

### T-011: Alibaba ECS provider
Owner: codex · Specs: [collector](specs/collector.md#alibaba-cloud)

- `collector/alibaba.py` implementing `Provider`, using the official SDKs.
- STS AssumeRole when `role_arn` is set; direct key otherwise.
- `NextToken` pagination, SG attribute lookup with per-scan cache, VPC and
  vSwitch lookup, EIP handling.

Acceptance: tests with an injected fake client and JSON fixtures cover
pagination, EIP vs public IP, SG rules both directions, and missing VPC data.

### T-012: Sync runner
Owner: codex · Specs: [collector](specs/collector.md#flow)

- `collector/runner.py`: accounts upsert, run/result rows, thread pool fan-out,
  upsert of instances, `present = false` marking, final run status.
- Works with any `Provider` (tests use a fake provider).

Acceptance: tests for idempotent re-run, partial failure, missing-instance
marking only after a successful scan, disabled accounts skipped.

### T-013: `cloudscope collect` CLI
Owner: codex · Specs: [collector](specs/collector.md)

- Typer command with `--account`, `--region`, `--trigger`.
- Exit code 0 for success/partial, 1 for failed; prints a summary table.

Acceptance: CLI test with fake providers.

### T-014: First real sync with test keys
Owner: human + claude

- Saheb fills `.env` and `config/accounts.yaml` locally with the test keys
  (never committed) and runs `cloudscope collect`.
- Claude reviews the output and fixes mapping issues found.

Acceptance: instances of the test accounts appear with correct fields.

## Phase 2: API, login and UI

### T-020: Users, passwords, `create-user` CLI
Owner: codex · Specs: [auth](specs/auth.md#passwords)

- argon2id hashing with rehash-on-login support.
- `cloudscope create-user <username> [--admin]` prompting for the password twice.

Acceptance: tests for hashing, verification, min length.

### T-021: Sessions and login API
Owner: codex · Specs: [auth](specs/auth.md), [api](specs/api.md#auth)

- `/api/auth/login`, `/logout`, `/me`, `/password`.
- Session table, cookie flags, sliding expiry, `X-Requested-With` check,
  per-user lockout and per-IP rate limit.
- `current_user` and `require_admin` dependencies.

Acceptance: tests for success, wrong password, lockout, expired session,
missing CSRF header, cookie flags.

### T-022: TOTP MFA
Owner: codex · Specs: [auth](specs/auth.md#totp-google-authenticator)

- `/mfa/setup` (URI + QR SVG), `/mfa/enable`, `/mfa/disable`, `/mfa/verify-login`.
- Fernet-encrypted secret, replay protection, 5-minute half-logged-in sessions.

Acceptance: tests using `pyotp` to generate codes, including replay and wrong
code; manual check that Google Authenticator accepts the QR.

### T-023: Instances, accounts, sync API
Owner: codex · Specs: [api](specs/api.md#instances)

- `/api/instances` with all filters, sort, pagination; `/api/instances/facets`;
  detail endpoint; `/api/accounts`; `/api/sync/runs*` incl. manual run.

Acceptance: tests for search by name, ID, IP and tag value; each filter; sort;
paging; 404 on unknown instance; 409 on concurrent manual sync.

### T-024: Admin users API
Owner: codex · Specs: [api](specs/api.md#users-admin)

Acceptance: non-admins get 403; tests for create, deactivate, reset MFA.

### T-030: UI: app shell, login, MFA step
Owner: codex · Specs: [ui](specs/ui.md#login-login)

- Layout with top nav (Search, Sync, Settings, user menu, logout).
- Route guard using `/api/auth/me`.

Acceptance: component tests for login success, MFA step, error display.

### T-031: UI: search page
Owner: codex · Specs: [ui](specs/ui.md#search-)

Acceptance: query and filters reflected in URL; table shows all default
columns; sorting and paging call the API correctly (tests with mocked API).

### T-032: UI: instance details page
Owner: codex · Specs: [ui](specs/ui.md#instance-details-instancesprovideraccountregionid)

Acceptance: all five sections render from fixture data for both an AWS and an
Alibaba instance; missing sections show "Not available".

### T-033: UI: sync status page
Owner: codex · Specs: [ui](specs/ui.md#sync-status-sync)

Acceptance: runs list, expandable results with errors, admin-only "Sync now".

### T-034: UI: settings
Owner: codex · Specs: [ui](specs/ui.md#settings-settings)

Acceptance: change password, MFA enable with QR + confirm, disable; admin
users table.

## Phase 3: Local Kubernetes

### T-040: Dockerfiles and image build in CI
Owner: codex · Specs: [deployment](specs/deployment.md#images)

Acceptance: both images build multi-arch in CI and push to GHCR on `main`;
containers run as non-root.

### T-041: Helm chart
Owner: codex · Specs: [deployment](specs/deployment.md#helm-chart-deployhelmcloudscope)

Acceptance: `helm lint` and `helm template` pass in CI; chart supports
in-cluster Postgres on/off, existingSecret, IRSA annotations, ingress on/off.

### T-042: Local cluster install guide and values
Owner: claude · Specs: [deployment](specs/deployment.md#local-cluster-kubeadm-3-nodes-on-proxmox)

- `deploy/helm/values.local.yaml` and `docs/install-local.md`.

### T-043: Deploy to local kubeadm cluster
Owner: human + claude

Acceptance: app reachable on the local network, CronJob runs every 15 min.

## Phase 4: EKS

### T-050: AWS role templates
Owner: codex · Specs: [cloud-access](specs/cloud-access.md#phase-4-aws-12-accounts)

- `deploy/aws/readonly-role.yaml` (StackSet template, parameter: hub role ARN,
  external ID) and `deploy/aws/hub-role.yaml`.

Acceptance: `cfn-lint` passes in CI; policies match cloud-access.md exactly.

### T-051: Alibaba RAM role Terraform
Owner: codex · Specs: [cloud-access](specs/cloud-access.md#phase-4-alibaba-cloud-8-accounts)

Acceptance: `terraform validate` passes; module takes the central account ID.

### T-052: Roll out roles in all accounts
Owner: human

- Deploy the StackSet to the 12 AWS accounts, apply the RAM role in the 8
  Alibaba accounts, fill `accounts` in the EKS values.

### T-053: EKS values
Owner: codex · Specs: [deployment](specs/deployment.md#eks-production)

Acceptance: `values.eks.yaml` example with Pod Identity service account,
External Secrets manifest, RDS `DATABASE_URL`, ALB ingress.
