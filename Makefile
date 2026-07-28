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
endif

# --- Stack ----------------------------------------------------------------

.PHONY: up
up: require-engine ## Start the full stack in the background
	$(COMPOSE) up -d

.PHONY: down
down: require-engine ## Stop the stack (volumes preserved)
	$(COMPOSE) down

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
clean: require-engine ## Stop the stack and delete its volumes (destroys data)
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
