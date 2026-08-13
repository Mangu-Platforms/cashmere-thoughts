# SkillVoice Studio — common operator & developer targets
# Usage: make <target>

.PHONY: help install test doctor clean coverage lint format check

PYTHON ?= python3
PIP    ?= $(PYTHON) -m pip

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Create venv and install (editable + lock)
	$(PYTHON) -m venv .venv
	. .venv/bin/activate && \
		$(PIP) install --upgrade pip && \
		$(PIP) install -r requirements.lock && \
		$(PIP) install -e ".[test]"
	@echo "Activate with: source .venv/bin/activate"

test: ## Run the full test suite with coverage
	$(PYTHON) -m pytest -q --cov=skillvoice --cov-report=term-missing

coverage: ## HTML coverage report
	$(PYTHON) -m pytest -q --cov=skillvoice --cov-report=html
	@echo "Open htmlcov/index.html"

doctor: ## Run skillvoice doctor (after install)
	skillvoice doctor

check: ## Quick health: doctor + tests
	skillvoice doctor
	$(MAKE) test

clean: ## Remove caches, coverage, build artifacts
	rm -rf .pytest_cache .coverage htmlcov dist build *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

format: ## Format with ruff (if installed)
	@command -v ruff >/dev/null && ruff format skillvoice tests || echo "Install ruff for formatting"

lint: ## Lint with ruff (if installed)
	@command -v ruff >/dev/null && ruff check skillvoice tests || echo "Install ruff for linting"
