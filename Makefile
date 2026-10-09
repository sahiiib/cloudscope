# Root task runner. Each target delegates to backend/ and frontend/ and skips
# a side that has not been scaffolded yet (T-002 / T-003).

HAS_BACKEND  := $(wildcard backend/pyproject.toml)
HAS_FRONTEND := $(wildcard frontend/package.json)

.PHONY: setup lint test dev-db migrate

setup:
ifneq ($(HAS_BACKEND),)
	cd backend && uv sync
endif
ifneq ($(HAS_FRONTEND),)
	cd frontend && npm ci
endif

lint:
ifneq ($(HAS_BACKEND),)
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy cloudscope
endif
ifneq ($(HAS_FRONTEND),)
	cd frontend && npm run lint && npx tsc --noEmit
endif

test:
ifneq ($(HAS_BACKEND),)
	cd backend && uv run pytest
endif
ifneq ($(HAS_FRONTEND),)
	cd frontend && npm test -- --run
endif

dev-db:
	docker compose up -d postgres

migrate:
	cd backend && uv run alembic upgrade head
