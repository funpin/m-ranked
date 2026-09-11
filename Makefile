# One entry point for the checks and the local stand.
# Toolchain: JDK 21, Node 24, Python 3.13+, Docker.

JAVA_HOME ?= /opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home
PYTHON    ?= .venv/bin/python
COMPOSE   := docker compose -f infra/compose.yaml -f infra/compose.local.yaml -p mranked-local

.PHONY: help venv test test-python test-backend test-frontend gates jar stand stand-prodcopy stand-down runner clean

help: ## List the available targets
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-16s %s\n", $$1, $$2}'

venv: ## Create the Python environment
	python3 -m venv .venv && $(PYTHON) -m pip install -q -r requirements.txt -r operations/requirements.txt

test-python: ## Python unit tests
	$(PYTHON) -m pytest tests anomaly_analysis -q

test-backend: ## Spring tests
	cd backend && JAVA_HOME=$(JAVA_HOME) ./mvnw -B test

test-frontend: ## Frontend lint, types, unit and browser tests
	cd frontend && pnpm check

test: test-python test-backend test-frontend ## Every fast gate

jar: ## Build the backend jar
	cd backend && JAVA_HOME=$(JAVA_HOME) ./mvnw -B verify

runner: ## Full integration runner on disposable databases (slow, needs Docker)
	JAVA_HOME=$(JAVA_HOME) $(PYTHON) -m migration.integration.run

gates: jar test runner ## Everything that must be green before a release

stand: ## Local stand on the seeded sample database
	bash infra/local/stack.sh up -d --build

stand-prodcopy: ## Local stand on a restored production copy: make stand-prodcopy COPY=<dir> ENV=<file>
	bash infra/local/prodcopy.sh $(COPY) $(ENV)

stand-down: ## Stop the local stand and keep its volumes
	$(COMPOSE) stop

clean: ## Remove build output and caches
	rm -rf backend/target frontend/.next frontend/test-results .pytest_cache
