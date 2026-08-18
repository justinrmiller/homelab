SHELL := /bin/bash
.DEFAULT_GOAL := help

# --- Container engine detection ------------------------------------------
# Prefer Docker, fall back to Podman. Override with CONTAINER_ENGINE=podman.
# Podman installs to /opt/podman/bin on macOS and is often not on PATH, so
# check the known locations as well as PATH.

PODMAN_CANDIDATES := $(shell command -v podman 2>/dev/null) /opt/podman/bin/podman /usr/local/bin/podman
DOCKER_BIN ?= $(shell command -v docker 2>/dev/null)
PODMAN_BIN ?= $(firstword $(wildcard $(PODMAN_CANDIDATES)))

ifeq ($(CONTAINER_ENGINE),docker)
  ENGINE := $(DOCKER_BIN)
  ENGINE_NAME := docker
else ifeq ($(CONTAINER_ENGINE),podman)
  ENGINE := $(PODMAN_BIN)
  ENGINE_NAME := podman
else ifneq ($(DOCKER_BIN),)
  ENGINE := $(DOCKER_BIN)
  ENGINE_NAME := docker
else ifneq ($(PODMAN_BIN),)
  ENGINE := $(PODMAN_BIN)
  ENGINE_NAME := podman
else
  ENGINE :=
  ENGINE_NAME := none
endif

COMPOSE := $(ENGINE) compose
UV := uv

.PHONY: engine
engine: ## Show which container engine was detected
ifeq ($(ENGINE),)
	@echo "No container engine found. Install Docker or Podman."
	@exit 1
else
	@echo "engine:  $(ENGINE_NAME)"
	@echo "binary:  $(ENGINE)"
	@echo "compose: $(COMPOSE)"
endif

.PHONY: require-engine
require-engine:
ifeq ($(ENGINE),)
	@echo "error: no container engine found (looked for docker, then podman)." >&2
	@echo "       install one, or set CONTAINER_ENGINE=docker|podman." >&2
	@exit 1
endif
ifeq ($(ENGINE_NAME),podman)
	@$(ENGINE) machine inspect >/dev/null 2>&1 || { \
		echo "note: no podman machine detected; run 'podman machine start' if on macOS." >&2; }
	@# Rootful and rootless podman keep entirely separate containers, images and
	@# volumes. With more than one connection it is easy to start the stack on
	@# one and then run ps/logs against the other, which looks like the stack
	@# vanished. Name the active one so that mismatch is visible.
	@conns=$$($(ENGINE) system connection list --format '{{.Name}}' 2>/dev/null | wc -l | tr -d ' '); \
	if [ "$${conns:-0}" -gt 1 ]; then \
		active=$${CONTAINER_CONNECTION:-$$($(ENGINE) system connection list \
			--format '{{.Name}} {{.Default}}' 2>/dev/null \
			| awk '$$2 == "true" {print $$1}')}; \
		echo "note: podman has $$conns connections; using '$$active'." >&2; \
		echo "      A stack started on a different connection is invisible here." >&2; \
		echo "      Pin one for every target with CONTAINER_CONNECTION=<name>." >&2; \
	fi
endif

# --- Stack ----------------------------------------------------------------

.PHONY: env-check
env-check: ## Verify .env exists and required secrets are set
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "Created .env from .env.example." >&2; \
		echo "error: set a real HASURA_GRAPHQL_ADMIN_SECRET in .env, then re-run." >&2; \
		exit 1; \
	fi
	@if ! grep -qE '^HASURA_GRAPHQL_ADMIN_SECRET=.+' .env; then \
		echo "error: HASURA_GRAPHQL_ADMIN_SECRET is not set in .env." >&2; \
		echo "       Hasura refuses to start without it: port 8080 would otherwise be" >&2; \
		echo "       unauthenticated read/write access to Postgres over GraphQL." >&2; \
		exit 1; \
	fi
	@if grep -qE '^HASURA_GRAPHQL_ADMIN_SECRET=(change-me|changeme)[[:space:]]*$$' .env; then \
		echo "error: HASURA_GRAPHQL_ADMIN_SECRET is still the placeholder value." >&2; \
		echo "       Set a real secret in .env before starting the stack." >&2; \
		exit 1; \
	fi

.PHONY: up
up: require-engine env-check ## Start the full stack in the background
	# Always --build. compose reuses whatever dashboard image already exists,
	# and the ./dashboard bind mount does not save you: an image built before
	# the streamlit/ -> dashboard/ rename runs /app/app.py, which the mount
	# never covers, so the container happily serves pre-rename code. Layer
	# caching makes this near-free unless pyproject.toml or uv.lock changed.
	# NO_BUILD=1 skips it.
	$(COMPOSE) up -d $(if $(filter 1,$(NO_BUILD)),,--build)

.PHONY: down
down: require-engine ## Stop the stack (volumes preserved)
	@$(COMPOSE) down || { \
		echo "" >&2; \
		echo "note: teardown failed; retrying once." >&2; \
		echo "      Rootless Podman intermittently cannot kill the shared network" >&2; \
		echo "      helper it uses for the stack ('rootless netns: kill network" >&2; \
		echo "      process: permission denied'). The retry normally succeeds; if" >&2; \
		echo "      it does not, restart the VM with 'podman machine stop && start'." >&2; \
		$(COMPOSE) down; \
	}

.PHONY: restart
restart: down up ## Restart the stack

.PHONY: build
build: require-engine ## Rebuild the dashboard image
	$(COMPOSE) build

.PHONY: pull
pull: require-engine ## Pull the latest pinned images
	$(COMPOSE) pull

.PHONY: ps
ps: require-engine ## Show service status
	$(COMPOSE) ps

.PHONY: logs
logs: require-engine ## Tail logs (SERVICE=name for one service)
	$(COMPOSE) logs -f $(SERVICE)

.PHONY: config
config: require-engine ## Validate and render the compose file
	$(COMPOSE) config

.PHONY: clean
clean: require-engine ## Stop the stack and PERMANENTLY DELETE its volumes
	@echo
	@echo "  WARNING: this runs 'compose down -v' and permanently deletes every"
	@echo "  volume for this stack. All data is lost:"
	@echo
	@echo "    postgres-18-data   all databases, including Hasura metadata"
	@echo "    kafka-data         all topics and messages"
	@echo "    valkey-data        all keys"
	@echo "    grafana-data       dashboards, users, saved settings"
	@echo "    floci-data         all S3 buckets and objects"
	@echo
	@echo "  To stop the stack without losing data, use 'make down' instead."
	@echo
	@if [ "$(FORCE)" = "1" ]; then \
		echo "  FORCE=1 set, skipping confirmation."; \
	else \
		read -r -p "  Type 'yes' to permanently delete this data: " reply; \
		if [ "$$reply" != "yes" ]; then echo "  Aborted. Nothing was deleted."; exit 1; fi; \
	fi
	$(COMPOSE) down -v

# --- Development ----------------------------------------------------------

.PHONY: install
install: ## Sync the local virtualenv from uv.lock
	$(UV) sync

.PHONY: lock
lock: ## Re-resolve dependencies and update uv.lock
	$(UV) lock

.PHONY: test
test: ## Run the test suite with coverage
	$(UV) run pytest

.PHONY: cov
cov: ## Run tests and write an HTML coverage report to htmlcov/
	$(UV) run pytest --cov-report=html

.PHONY: lint
lint: ## Lint with ruff
	$(UV) run ruff check .

.PHONY: fmt
fmt: ## Format with ruff
	$(UV) run ruff format .

.PHONY: fmt-check
fmt-check: ## Verify formatting without writing
	$(UV) run ruff format --check .

.PHONY: typecheck
typecheck: ## Type-check with ty (advisory; ty is pre-1.0)
	-$(UV) run ty check

.PHONY: check
check: lint fmt-check typecheck test ## Run everything CI runs

.PHONY: dev
dev: ## Run the dashboard locally against localhost services
	$(UV) run streamlit run dashboard/app.py

.PHONY: help
help: ## List available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'
