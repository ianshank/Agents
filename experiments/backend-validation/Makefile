# Hand-written Makefile for the backend-validation experiment (member-package style).
# Quality targets delegate to the GENERATED gate script (scripts/quality-gate.sh) so local
# and CI checks can never drift; phase targets drive the experiment CLI.
.DEFAULT_GOAL := help
PYTHON ?= python3

.PHONY: help install install-offline format lint typecheck test coverage check \
        preflight deploy l1 l2 airgap report all-phases down status isolation pin-digests

help: ## Show available targets
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*##/ {printf "  %-16s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Editable install with SDK extras + the root harness (needed for L2 coverage)
	$(PYTHON) -m pip install -e ".[dev,langfuse,opik]"
	$(PYTHON) -m pip install -e ../../

install-offline: ## Editable install without backend SDKs (enough for the quality gate)
	$(PYTHON) -m pip install -e ".[dev]"
	$(PYTHON) -m pip install -e ../../

format: ## Auto-format the experiment code
	$(PYTHON) -m ruff format backend_validation tests

lint: ## Lint via the generated gate
	./scripts/quality-gate.sh lint

typecheck: ## Typecheck via the generated gate
	./scripts/quality-gate.sh typecheck

test: ## Offline unit suite via the generated gate
	./scripts/quality-gate.sh test

coverage: ## Offline suite with the 95% branch-coverage floor
	./scripts/quality-gate.sh coverage

check: ## The full quality gate (lint + typecheck + coverage + extras)
	./scripts/quality-gate.sh all

# ------------------------------------------------------------------ experiment phases
preflight: ## P0: env + TCB validation; STOPS (exit 3) until the human sign-off exists
	$(PYTHON) -m backend_validation.cli preflight

deploy: ## P1: stand up langfuse + opik + judge stacks (BACKEND=<id> for one)
	$(PYTHON) -m backend_validation.cli deploy $(if $(BACKEND),--backend $(BACKEND),)

l1: ## P2: L1 capability probes + negative controls
	$(PYTHON) -m backend_validation.cli l1 $(if $(BACKEND),--backend $(BACKEND),)

l2: ## P3: integration probes through the harness sink seam (precondition-gated)
	$(PYTHON) -m backend_validation.cli l2 $(if $(BACKEND),--backend $(BACKEND),)

airgap: ## P4: egress-blocked L1 re-run, dual-scored (as-shipped vs opt-out)
	$(PYTHON) -m backend_validation.cli airgap $(if $(BACKEND),--backend $(BACKEND),)

report: ## P5: render claimed-vs-observed + effort metrics + airgap reports
	$(PYTHON) -m backend_validation.cli report

all-phases: ## P0..P5 chained; stops on the first BLOCKED/HALT
	$(PYTHON) -m backend_validation.cli all

down: ## Tear down every experiment stack
	$(PYTHON) -m backend_validation.cli down

status: ## Show stack/container status
	$(PYTHON) -m backend_validation.cli status

isolation: ## PR-scoped zero-writes check against origin/main
	$(PYTHON) -m backend_validation.cli isolation --base-ref origin/main

pin-digests: ## Resolve compose image tags to sha256 digests (run where the registry is reachable)
	$(PYTHON) -m backend_validation.cli pin-digests
