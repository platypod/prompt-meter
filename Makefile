# prompt-meter — Unix dev + CI convenience only (assumes a .venv/bin layout +
# POSIX tools). END USERS on any OS install the wheel and use the `prompt-meter`
# CLI instead — see README.md "Install". `make build` is the CI artifact target.
# `make help` lists targets.

PYTHON   ?= python3
VENV     ?= .venv
BIN       = $(VENV)/bin
PROVIDER ?= claude-code
OWNER    ?= $(USER)
ARGS     ?=

# For shipping to a local cluster via a gateway port-forward:
#   kubectl -n dev-platypod port-forward svc/opentelemetry-collector-gateway 4317:4317
DEV_ENDPOINT ?= localhost:4317

.DEFAULT_GOAL := help

.PHONY: help venv install build clean list-providers dry-run ship ship-dev \
        setup-claude-hook print-claude-hook lint test

help:            ## Show this help
	@grep -E '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

venv:            ## Create the virtualenv
	$(PYTHON) -m venv $(VENV)

install: venv    ## Install the package (editable) + dev tools into the venv
	$(BIN)/pip install -U pip
	$(BIN)/pip install -e '.[dev]'

build:           ## Build the wheel + sdist into dist/
	$(BIN)/pip install -U build
	$(BIN)/python -m build

list-providers:  ## List available providers
	$(BIN)/prompt-meter --list-providers

dry-run:         ## Parse sessions and report what WOULD ship (no network)
	$(BIN)/prompt-meter --provider $(PROVIDER) --owner $(OWNER) --dry-run $(ARGS)

ship:            ## Ship telemetry (PROVIDER=, OWNER=, ARGS= to override)
	$(BIN)/prompt-meter --provider $(PROVIDER) --owner $(OWNER) $(ARGS)

ship-dev:        ## Ship to a local port-forwarded gateway (insecure, OWNER=)
	OTEL_EXPORTER_OTLP_ENDPOINT=$(DEV_ENDPOINT) \
	  $(BIN)/prompt-meter --provider $(PROVIDER) --owner $(OWNER) --insecure --reset $(ARGS)

setup-claude-hook: ## Add a Claude Code SessionEnd hook that ships on every session close
	$(BIN)/python -m promptmeter.contrib.claude_hook install --owner $(OWNER)

print-claude-hook: ## Print the SessionEnd hook snippet without modifying anything
	$(BIN)/python -m promptmeter.contrib.claude_hook print --owner $(OWNER)

lint:            ## Lint with ruff
	$(BIN)/ruff check src

test:            ## Run the test suite
	$(BIN)/pytest -q

clean:           ## Remove build artifacts and caches
	rm -rf build dist *.egg-info src/*.egg-info .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
