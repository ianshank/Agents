# Unsigned experiment. Not wired into the repo-root `check-all`.
PYTHON ?= python3

.PHONY: check update help

help:
	@echo "check   — run sqlite sketches against fixtures (stdlib only)"
	@echo "update  — regenerate expected.json from fixtures"

check: ## Golden-file SQL sketches (no DuckDB, no ClickHouse)
	$(PYTHON) check_offline.py

update:
	$(PYTHON) check_offline.py --update
