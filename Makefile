# SOC 2 Access Reviews — developer tasks
# Override the ruff invocation if you prefer a local install: make RUFF=ruff lint
RUFF ?= ruff
PYTHON ?= python3
PROJECTS := jira-slack-access-managers shared-drive-file-review

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

.PHONY: install
install: ## Install runtime deps for both subprojects
	pip install -r jira-slack-access-managers/requirements.txt \
	            -r shared-drive-file-review/requirements.txt

.PHONY: install-dev
install-dev: ## Install dev tooling (ruff)
	pip install -r requirements-dev.txt

.PHONY: lint
lint: ## Lint with ruff
	$(RUFF) check .

.PHONY: fix
fix: ## Auto-fix lint issues
	$(RUFF) check --fix .

.PHONY: format
format: ## Format the code in place
	$(RUFF) format .

.PHONY: format-check
format-check: ## Check formatting without writing
	$(RUFF) format --check .

.PHONY: check
check: lint format-check compile ## Run everything CI runs

.PHONY: compile
compile: ## Byte-compile all sources (catches syntax errors)
	$(PYTHON) -m compileall $(PROJECTS)

.PHONY: clean
clean: ## Remove caches and build artifacts
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type f -name '*.py[co]' -delete
