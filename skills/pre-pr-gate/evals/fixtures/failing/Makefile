# Fixture Makefile for pre-pr-gate's behavioral evals: a `pre-pr` target that
# always fails, so the wrapper's failure path (non-zero exit, "FAILED" report,
# the underlying output still surfaced) is tested without running the real
# ~13-command battery.
.PHONY: pre-pr

pre-pr:
	@echo "fixture: a check failed"
	@exit 1
