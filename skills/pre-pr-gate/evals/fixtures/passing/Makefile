# Fixture Makefile for pre-pr-gate's behavioral evals: a `pre-pr` target that
# always succeeds, so the wrapper's success path (exit 0, "OK" report) is
# tested without running the real ~13-command battery.
PRE_PR_BASE_REF ?= origin/main

.PHONY: pre-pr

pre-pr:
	@echo "fixture: all checks passed (base-ref=$(PRE_PR_BASE_REF))"
