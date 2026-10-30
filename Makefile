# Convenience wrappers — every target runs inside Docker. No host Python, ever.
.DEFAULT_GOAL := help

COMPOSE := docker compose
# --no-deps so lint/type/test don't spin up db+redis
RUN     := $(COMPOSE) run --rm --no-deps api

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

lock: ## (Re)generate requirements.lock from pyproject.toml (in a throwaway container)
	docker run --rm -v "$$PWD":/w -w /w python:3.12-slim-bookworm \
		sh -c "pip install -q 'uv>=0.5,<0.6' && uv pip compile --upgrade pyproject.toml --extra dev -o requirements.lock"

build: ## Build the api image
	$(COMPOSE) build api

up: ## Start the api (http://localhost:8000/health)
	$(COMPOSE) up api

stack: ## Start the whole stack (db, redis, api, worker, beat, mailhog, minio)
	$(COMPOSE) up

down: ## Stop everything
	$(COMPOSE) down

migrate: ## Apply database migrations
	$(COMPOSE) run --rm api alembic upgrade head

seed: ## Seed default permissions + levels (idempotent)
	$(COMPOSE) run --rm api python -m app.console seed

keys: ## Generate the RS256 JWT keypair
	$(RUN) python -m app.console generate-keys

superadmin: ## Create a superadmin (EMAIL=... [PASSWORD=...])
	$(COMPOSE) run --rm api python -m app.console create-superadmin --email "$(EMAIL)" $(if $(PASSWORD),--password "$(PASSWORD)",)

worker: ## Run a Celery worker
	$(COMPOSE) up worker

beat: ## Run the Celery beat scheduler
	$(COMPOSE) up beat

lint: ## ruff check
	$(RUN) ruff check .

fmt: ## ruff format (writes changes)
	$(RUN) ruff format .

fmt-check: ## ruff format --check
	$(RUN) ruff format --check .

type: ## mypy (strict)
	$(RUN) mypy

test: ## pytest
	$(RUN) pytest -q

cov: ## pytest with coverage report (needs db+redis up)
	$(COMPOSE) run --rm api pytest -q --cov=app --cov-report=term-missing

security: ## bandit + pip-audit
	# CVE-2025-65896 (asyncmy): no fixed release exists yet; tracked + accepted.
	$(RUN) sh -c "bandit -q -c pyproject.toml -r app && pip-audit --ignore-vuln CVE-2025-65896"

check: lint fmt-check type test ## Run all CI gates
	@echo "All gates passed."

.PHONY: help lock build up stack down migrate seed keys superadmin worker beat \
        lint fmt fmt-check type test cov security check
