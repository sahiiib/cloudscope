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
| T-013 | `cloudscope collect` CLI | codex | T-012 | done |
| T-014 | First real sync with test keys | human + claude | T-013, T-011 | done |
| T-020 | Users, passwords, `create-user` CLI | codex | T-005 | done |
| T-021 | Sessions and login API | codex | T-020 | done |
| T-022 | TOTP MFA | codex | T-021 | done |
| T-023 | Instances, accounts, sync API | codex | T-021, T-012 | done |
| T-024 | Admin users API | codex | T-022 | done |
| T-030 | UI: app shell, login, MFA step | codex | T-003, T-022 | done |
| T-031 | UI: search page | codex | T-030, T-023 | done |
| T-032 | UI: instance details page | codex | T-031 | done |
| T-033 | UI: sync status page | codex | T-030, T-023 | done |
| T-034 | UI: settings (password, MFA, users) | codex | T-030, T-024 | done |
| T-040 | Dockerfiles and image build in CI | codex | T-013, T-003 | done |
| T-041 | Helm chart | codex | T-040 | done |
| T-042 | Local cluster install guide and values | claude | T-041 | done |
| T-043 | Deploy to local kubeadm cluster | human + claude | T-042 | done |
| T-050 | AWS read-only role StackSet + hub role templates | codex | T-010 | done |
| T-051 | Alibaba RAM role Terraform | codex | T-011 | done |
| T-052 | Roll out roles in all accounts | human | T-050, T-051 | todo |
| T-053 | EKS values: Pod Identity, external secret, RDS option | codex | T-041, T-050 | done |
| T-060 | Accounts in the database: admin API, file + UI sources | codex | T-043 | done |
| T-061 | UI: Settings → Cloud accounts | codex | T-060 | done |
| T-062 | Show account name, cloud alias and ID per instance | codex | T-060 | done |
| T-063 | Fork collaboration and coordinated release workflow | codex | T-040, T-041 | done |
| T-064 | Reconcile fork account schema into upstream (issue #38) | codex | T-062 | done |
| T-066 | Ensure rebuilt backend images contain changed source | codex | T-040 | done |
| T-067 | Harden image rebuild regression and lint coverage | codex | T-040 | done |
| T-069 | Read-only load balancer inventory | codex | T-060, T-062 | review |
| T-068 | Modern console and selectable appearance | codex | T-061 | review |

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

Result (2026-10-10): `regions: all` synced 17 AWS and 34 Alibaba regions, all
`success`, 34 instances in total. Every field matched the consoles, so no mapping
fixes were needed. A second run kept the total at 34.

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

- `deploy/helm/values.local.yaml` and `docs/install-local.md`. (Delivered as
  `values.local.example.yaml`; the filled-in `values.local.yaml` is git-ignored
  because it holds real account IDs.)

### T-043: Deploy to local kubeadm cluster
Owner: human + claude

Acceptance: app reachable on the local network, CronJob runs every 15 min.

Result (2026-10-12): installed with `sha-180c68a…` images. Reachable on the LAN
through the Istio gateway (NodePort 31008) and, until the EKS move, through a
Cloudflare tunnel (test only, no Cloudflare Access by Saheb's choice). Admin has MFA. Manual and scheduled
collector runs completed with all regions `success`. The first install found
the service-link env collision fixed in #30; guide fixes in #31.

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

## Phase 5: Admin features

### T-060: Accounts in the database: admin API, file + UI sources
Owner: codex · Specs: [accounts](specs/accounts.md), [data-model](specs/data-model.md#accounts),
[api](specs/api.md#accounts), [collector](specs/collector.md#flow)

- Alembic migration adding `source`, `role_arn`, `external_id`, `regions`,
  `created_at`, `updated_at` to `accounts`. Existing rows become `source = file`,
  `regions = "all"`; the next collect run fills their file values.
- File sync touches only `source = file` rows; file/UI conflicts follow
  accounts.md. The collector (CLI, CronJob and "Sync now") scans every enabled
  row from the database. A missing accounts file means no file accounts.
- `POST /api/accounts`, `PATCH /api/accounts/{provider}/{account_id}` and
  `POST /api/accounts/{provider}/{account_id}/test`, admin full session + CSRF.
  `GET /api/accounts` gains `source`, `role_arn`, `external_id`, `regions`.
- Access test: provider methods in `cloudscope/collector/` (assume role if set,
  then list regions), 30 s timeout, sanitized errors, injected clients.
- Audit log lines as in accounts.md.

Acceptance:
- Tests (moto for AWS, fakes for Alibaba) cover: create/patch/validation (each
  rule in the accounts.md table, including the ARN account ID check), 409 for
  duplicates and for editing a `file` account, non-admin 403, missing CSRF 403.
- A collect run with a file account and a UI account scans both; removing the
  file entry disables only the file account; a file entry that collides with a
  UI account is skipped and logged.
- Disabled UI accounts are not scanned; their instances are untouched.
- The access test reports success and a sanitized `AccessDenied`-style failure
  without writing inventory.
- No new cloud API call beyond `AssumeRole` and `DescribeRegions`; nothing writes
  to a cloud account.

### T-061: UI: Settings → Cloud accounts
Owner: codex · Specs: [ui](specs/ui.md#settings-settings), [accounts](specs/accounts.md)

- Admin-only "Cloud accounts" section in Settings, built on the T-060 API.
- Table: provider, name, account ID, regions, role ARN, source, enabled, last
  success, instance count.
- Add form and edit form for `ui` accounts (provider and account ID read-only when
  editing). Client-side checks mirror accounts.md; server 422/409 messages show
  inline next to the field.
- `file` accounts are read-only with a "Managed by accounts.yaml" label.
- Enable/disable with an inline confirmation; "Test access" shows ok + region
  count, or the sanitized error, inline.
- After create/edit/enable/disable, the accounts list, the Search account facet
  and the Sync page data refresh.

Acceptance: colocated tests cover admin vs non-admin visibility, create (success,
422 field error, 409), edit of a `ui` account, read-only `file` account,
enable/disable confirmation, and both test-access outcomes.

### T-062: Show account name, cloud alias and ID per instance
Owner: codex · Specs: [accounts](specs/accounts.md#cloud-account-alias),
[api](specs/api.md#instances), [ui](specs/ui.md#search-), [cloud-access](specs/cloud-access.md)

- Migration adding `accounts.cloud_alias` and `accounts.cloud_alias_checked_at`.
- Provider methods in `cloudscope/collector/` reading the alias
  (`iam:ListAccountAliases`, RAM `GetAccountAlias`), called once per account per
  run; failures keep the old value, are logged with the error code and never fail
  a region scan.
- Add `iam:ListAccountAliases` to `deploy/aws/readonly-role.yaml` and to the
  read-only policy block in cloud-access.md (a test checks they match), and a custom
  `ram:GetAccountAlias` policy to `deploy/alibaba/readonly-role.tf`. Nothing else
  changes in the roles.
- API: `account_alias` on instance list items and detail, `cloud_alias` on
  `/api/accounts`; `q` also matches account name, alias and ID.
- Search: separate Account, Account alias and Account ID columns (copy button on
  the ID). Details Summary: separate Account name, Account alias and Account ID
  rows. T-061's accounts table shows the alias too, if T-061 is merged first;
  otherwise T-061 adds it.

Acceptance:
- Tests (moto for AWS, fakes for Alibaba) cover: alias stored; no alias -> null;
  AccessDenied keeps the old alias, logs the code, and the region scans still
  succeed.
- `q` finds instances by account name, alias and ID.
- UI tests show the three account fields in Search and Details for both an AWS
  and an Alibaba fixture, and "–" when the alias is null.
- cfn-lint and terraform validate pass; the only role changes are the two new
  read-only permissions.

Also in T-062, small fixes from the T-060/T-061 reviews (#33, #34):
- Access test: label assume-role failures `Assume role failed: <code>` instead
  of `Region discovery failed`, so the "<phase>" in accounts.md is correct.
- Access test clients: short timeouts and few retries (for example connect 5 s,
  read 10 s, 2 attempts) so a timed-out test does not keep a worker busy.
- File sync: change `updated_at` only when a file account really changed.
- Audit/log lines: write `account_id` the same way everywhere (unquoted).
- Account form: trim before comparing regions with `all` (`" all"` must not
  become a region named "all").

### T-063: Fork collaboration and coordinated release workflow
Owner: codex · Assigned by fork contributor · Spec: [CONTRIBUTING.md](../CONTRIBUTING.md)

- Document upstream ownership, one task per branch/PR and maintainer review.
- Add task and PR templates with validation, migration and recovery expectations.
- Describe maintainer-owned branch protection, isolated environments and release
  promotion using the same tested image digests.

Acceptance: contribution guide links and commands match the repository; templates
are usable on GitHub; deployment/migration rules preserve data and avoid parallel
upgrades. Documentation distinguishes proposals from settings actually enabled.

### T-064: Reconcile fork account schema into upstream (issue #38)
Owner: codex (yerevanstar) · Specs: [accounts](specs/accounts.md),
[data-model](specs/data-model.md#accounts) · Issue: #38

Implementation: [rollout and stored-key guard](fork-reconciliation.md). Migration
0006 refuses before mutation while stored keys exist. The operator follows the
documented transactional clearing step after verifying the backup, then migrates
and verifies role/base access in Settings. The role-only design remains as decided
below; this task does not depend on the separate per-account-key proposal.

Some databases ran a fork's `0004` (accounts with `connection_config` jsonb and
`credentials_encrypted` text) and then upstream `0005` (alias). They report head
`0005` but lack upstream `0004` columns, so the upstream API cannot read accounts.

Decision (Saheb, 2026-10-12): the upstream model stays. Accounts hold no access
keys or secrets; base credentials come from the runtime environment and each
account may name a role to assume. The fork's per-account stored keys and its
Accounts implementation are not carried over.

- New migration `0006` (revises `0005`, new unique ID; `0004`/`0005` untouched)
  that inspects the `accounts` table and is a no-op on a normal upstream database:
  - Adds any missing upstream `0004` column, default and check constraint exactly
    as `0004_account_sources.py` defines them.
  - If `connection_config` exists, copies `role_arn`, `external_id` and `regions`
    from it into the new columns only when the value passes the accounts.md
    validation for that row's provider and account ID; otherwise keeps null /
    `"all"`. Logs counts only, never values.
  - Every reconciled row gets `source = file` (the next collect run disables rows
    that are not in `accounts.yaml`; admins can re-add them in the UI).
  - Drops `connection_config` and `credentials_encrypted`. Before dropping, logs
    `event=reconcile_dropped_credentials count=<n>`, never values or IDs. This
    drop is intended: stored keys are removed by decision, not by accident.
  - Fails with a clear message if it finds any other non-upstream column or
    table instead of guessing.
  - `downgrade()` is a no-op with a comment: recovery is restoring the backup.
- Rows, instances, sync history, users, sessions and MFA are preserved.

Acceptance:
- Tests build a hybrid database (upstream `0003` + fork columns + upstream `0005`
  columns, stamped `0005`) with placeholder IDs, run `upgrade head`, and check:
  upstream schema matches a fresh upstream database (compare
  `pg_dump --schema-only` or the SQLAlchemy inspector), valid config values are
  copied, invalid ones are not, both fork columns are gone, and instances,
  sync results and users survive.
- A fresh upstream database upgrades through `0006` unchanged.
- The PR describes the rollout: backup, restore into a disposable database and
  run the migration there first, then upgrade the shared release to the
  upstream image. An account that used a stored key needs a role ARN (or the
  base credentials) afterwards; the access test in Settings shows it.

### T-066: Ensure rebuilt backend images contain changed source
Owner: codex · Assigned by fork contributor · Spec: [deployment](specs/deployment.md)

The final project installation must build the copied Python source rather than
reuse a cached wheel keyed by unchanged project metadata. Keep dependency-layer
caching. A container regression check changes source twice with identical
pyproject.toml and verifies both installed markers; CI publishing waits for it.

Acceptance: the rebuild regression and existing image smoke pass, scripts lint,
and no application/runtime configuration or database change is introduced.

### T-067: Harden image rebuild regression and lint coverage
Owner: codex · Assigned by contributor · Spec: [deployment](specs/deployment.md)

Follow up on the non-blocking review of merged PR #42: format the rebuild script
with the backend's 100-column Ruff configuration and include it in local/CI lint;
use a tag per source marker and remove both test images; use explicit exit status
instead of assertions so validation still works with Python optimization.

Acceptance: local two-build Docker regression passes with Python -O, successful
and failed checks return correct exit codes, both generated image tags are cleaned,
and explicit-config Ruff lint/format pass. No runtime or database change.

### T-069: Read-only load balancer inventory
Owner: codex · Assigned by fork contributor · Spec: [load balancers](specs/load-balancers.md)

Acceptance: AWS ELBv2/Classic and Alibaba CLB/ALB/NLB adapters, safe pagination,
independent atomic snapshots with retained data on failure, authenticated paginated
search/details/status API, searchable UI with explicit completeness/error states.
Additive migration matches ORM; fake SDK and Postgres tests cover permissions,
identity, pagination, missing/reappearance and auth. Lint/tests/build pass.
Collection is opt-in and no shared deployment/IAM change is made by this PR.
### T-068: Modern console and selectable appearance
Owner: codex · Assigned by fork contributor · Spec: [ui](specs/ui.md#modern-console-t-068)

Acceptance: responsive sidebar, dedicated admin Accounts route, consistent visual
styles for Search, Settings, Sync and details, accessible keyboard navigation,
light/dark/system selection on login and in the console. Only appearance is
persisted locally; no inventory or credentials. Existing account behavior and
authentication remain intact. Tests and frontend lint/build pass.
