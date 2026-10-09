# AGENTS.md

Instructions for coding agents (Codex, Claude Code) working in this repository.
Humans: see [README.md](README.md).

## Before you start a task

1. Read [docs/TASKS.md](docs/TASKS.md) and pick **one** task whose owner is
   `codex` (or the one you were assigned), whose status is `todo`, and whose
   dependencies are all `done`.
2. Read every spec the task links to. The specs in `docs/specs/` are the source
   of truth. If a spec is unclear, wrong or blocks you, do not silently change
   the design: implement the most reasonable reading, and list the question
   under "Open questions" in the PR description.
3. Do not start tasks owned by `claude` or `human`.

## How to deliver a task

- One task = one branch = one pull request.
- Branch name: `codex/T-XXX-short-slug` (Claude uses `claude/T-XXX-short-slug`).
- PR title: `T-XXX: <task title>`.
- PR description must contain:
  - Task ID and link to its section in `docs/TASKS.md`
  - What changed (short)
  - How it was tested (commands and results)
  - Open questions / deviations from the spec
- In the same PR, change the task's status in `docs/TASKS.md` from `todo` to
  `review`. Only the reviewer sets `done`.
- Keep PRs focused. Do not refactor unrelated code or reformat files you did
  not otherwise change.
- Every PR is reviewed by Claude (and Saheb) before merge. Never merge your own PR.

## Definition of done (every task)

- All acceptance criteria in the task are met.
- New code has tests. `make test` passes.
- `make lint` passes (ruff + mypy for backend, eslint + tsc for frontend).
- No secrets, account IDs of real accounts, or real IPs in code, tests or
  fixtures. Use placeholders like `111111111111`, `i-0123456789abcdef0`,
  `10.0.0.1`.
- Docs updated if behavior or config changed (README, specs, `.env.example`).

## Commands

```bash
make setup      # install backend (uv) and frontend (npm) deps
make lint       # ruff, mypy, eslint, tsc
make test       # pytest + vitest
make dev-db     # start local postgres via docker compose
make migrate    # alembic upgrade head
```

(These targets are created by T-001 to T-004. Until then use the tools directly.)

## Code conventions

### Backend (Python)
- Python 3.12, `uv`, code in `backend/cloudscope/`, tests in `backend/tests/`.
- Type hints everywhere; mypy strict for `cloudscope/`.
- ruff for lint and format (line length 100).
- SQLAlchemy 2.0 style (`select()`, `Mapped[...]`), sync engine.
- Every schema change is an Alembic migration; never edit an applied migration.
- Cloud SDK calls only inside `cloudscope/collector/`. Clients are injected so
  tests can pass fakes.
- AWS tests use `moto`. Never call real cloud APIs in tests.
- Log with the stdlib `logging` module, structured as `key=value`. Never log
  credentials, session tokens, passwords or TOTP codes.

### Frontend (TypeScript)
- Code in `frontend/src/`. Strict TypeScript, no `any` without a comment.
- Data fetching with TanStack Query; API types in `frontend/src/api/types.ts`
  must match `docs/specs/api.md`.
- Components are small and live next to their tests (`*.test.tsx`).

## Security rules (hard)

- Never commit or print credentials. `.env`, `config/accounts.yaml`,
  `secrets/`, `*.pem`, `*.key` are git-ignored; keep it that way.
- Cloud access is read-only. Never add a call that creates, modifies or deletes
  cloud resources.
- Do not weaken auth (session cookie flags, argon2, TOTP checks, lockout) to
  make a test pass.
- Do not add new dependencies without a one-line reason in the PR description.
