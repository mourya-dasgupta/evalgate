PYTHON ?= python
SRC := src tests examples

.PHONY: install lint format typecheck test cov demo demo-record clean help

help:  ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

install:  ## Install EvalGate in editable mode with dev dependencies
	$(PYTHON) -m pip install -e ".[dev]"

lint:  ## Run ruff lint and format checks
	$(PYTHON) -m ruff check $(SRC)
	$(PYTHON) -m ruff format --check $(SRC)

format:  ## Auto-format and auto-fix lint issues
	$(PYTHON) -m ruff format $(SRC)
	$(PYTHON) -m ruff check --fix $(SRC)

typecheck:  ## Run mypy --strict on src/
	$(PYTHON) -m mypy --strict src

test:  ## Run the test suite
	$(PYTHON) -m pytest -q

cov:  ## Run tests with coverage (fails under 90%)
	$(PYTHON) -m pytest -q --cov=evalgate --cov-report=term-missing --cov-fail-under=90

demo:  ## Run the support-triage demo story (v1 baseline -> v2 FAIL -> v1 PASS)
	EVALGATE="$(PYTHON) -m evalgate" bash examples/support-triage/demo.sh

demo-record:  ## Re-record the demo cassettes with the simulated model
	EVALGATE="$(PYTHON) -m evalgate" bash examples/support-triage/record.sh

clean:  ## Remove build, cache and run artefacts
	rm -rf build dist .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov coverage.xml
	rm -rf examples/support-triage/.evalgate/runs
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
