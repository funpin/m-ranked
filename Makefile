# One entry point for Python, frontend and the local stand.
# Toolchain: Node 24, Python 3.13+, Docker.

PYTHON  ?= .venv/bin/python
COMPOSE := docker compose --env-file infra/local/compose.env.example -f infra/compose.yaml -f infra/compose.local.yaml -p mranked-local

.PHONY: help venv test test-python test-frontend gates stand stand-down clean

help: ## List the available targets
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-16s %s\\n", $$1, $$2}'

venv: ## Create the Python environment
	python3 -m venv .venv && $(PYTHON) -m pip install -q -r requirements.txt -r operations/requirements.txt

test-python: ## Python unit and contract tests
	$(PYTHON) -m pytest tests anomaly_analysis -q

test-frontend: ## Frontend lint, types, unit and browser tests
	cd frontend && pnpm check

test: test-python test-frontend ## Every gate

gates: test ## Everything that must be green before a release

stand: ## Local FastAPI/PostgreSQL/Next.js stand
	bash infra/local/stack.sh up -d --build

stand-down: ## Stop the local stand and keep its volumes
	$(COMPOSE) stop

clean: ## Remove build output and caches
	rm -rf frontend/.next frontend/test-results .pytest_cache
