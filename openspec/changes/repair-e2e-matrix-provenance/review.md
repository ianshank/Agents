# Review: repair-e2e-matrix-provenance

**Date:** 2026-09-08 · **Track:** agent lane · **Status:** implementation in this PR

## Pass 1 — spec vs tree

- Provenance is gated as reachable (object exists, ancestor of HEAD). SHA == HEAD is
  not a freshness comparison (ADR 0033 §3). `git merge-base --is-ancestor A A` is true;
  `--check` after `--update` in the same commit is allowed so CI pytest does not recreate
  the equal-to-HEAD deadlock.
- Missing objects skip, they do not fail (`skip_missing_objects=True`).
- Monotonicity refuses an observed-step or per-suite test-count drop unless
  `MONOTONICITY_WAIVERS` names that exact pair. ERRATA stamps are in
  `PROVENANCE_SHA_WAIVERS`.
- Timeouts live on `GitQueryConfig.timeout_seconds`, wired from
  `SubprocessConfig.git_timeout_seconds` at the CLI.

## Pass 2 — what this does not do

Does not regenerate `docs/e2e-matrix/` (needs a real e2e report). Does not implement
WS-1 or the production flywheel.
