# 0003 — Adopt skill-creator evals as the release gate; stdlib JSONL logging instead of structlog

- Status: **Accepted.**
- Date: 2026-07-03
- Related: `docs/plans/claude-foundation/PLAN.md` in `ianshank/Agents` (§2.2, §6.2 M5);
  REVIEW.md findings F2 (buy, don't build, for evals) and F5 (behavioral evals are not
  merge gates); ADR 0002 (hook fail modes).

## Context

Two coupled build-vs-buy calls. First, every skill must ship behavioral evals; the plan
originally sketched a custom Pydantic/Protocol-DI eval runner, but the official
skill-creator plugin already implements the whole convention — per-skill
`evals/evals.json` (the open agentskills.io format), isolated subagent execution per
case, `grading.json` with pass/fail evidence — and REVIEW.md F2 flagged the custom
runner as the plan's largest duplication of maintained tooling. Second, hooks and tools
need structured logging; the plan's soft constraints preferred `structlog`, but hook
scripts execute inside arbitrary consumer environments where no third-party package can
be assumed installed, and a hook import error would trip ADR 0002's fail modes for no
functional gain.

## Decision

### (a) Eval integration: thin wrapper over skill-creator, release-blocking only

1. Skills ship `evals/evals.json` in the **skill-creator / agentskills.io format**,
   with at least 3 cases per skill. No custom eval file format.
2. `foundation_tools.eval_gate` is a **thin wrapper only**: it invokes skill-creator
   evals headlessly, parses each skill's `grading.json`, and exits nonzero unless
   assertion pass rate is 100% on the release candidate. It contains no grading logic.
3. Behavioral evals are **RELEASE-blocking, not merge-blocking** (REVIEW F5): they are
   non-deterministic and require API access and credits, so a per-PR 100% gate would
   flake and accumulate cost. Per-PR CI runs only the deterministic gates; the eval
   gate runs nightly and before any version tag is cut.
4. Fallback to a custom runner is permitted only if skill-creator proves
   non-scriptable in CI, and would supersede this ADR.

### (b) Logging: stdlib `logging` emitting JSONL, not structlog

5. `foundation_tools.jsonlog` builds JSONL structured logging on **Python stdlib
   `logging`** (a JSON formatter over standard handlers). Hook scripts use the
   dependency-free equivalent in `hooks/_lib.py`, keeping hooks importable with
   **zero third-party dependencies** on any consumer machine with Python 3.11+.
6. Log activation stays env-driven: records are written only when
   `CLAUDE_FOUNDATION_LOG_DIR` is set, one JSON object per line.
7. PLAN.md's structlog preference was a **soft constraint** (§2.2); this deviation is
   recorded here rather than silently absorbed. structlog remains acceptable for
   future dev-only tooling that never runs in consumer environments.

## Consequences

- M5 collapsed from "build an eval framework" to "integrate one"; upstream
  improvements (benchmarking, A/B comparison, trigger-rate tuning) come for free.
- Releases depend on skill-creator remaining scriptable and on API availability; a
  broken eval run blocks tagging, never merging.
- The JSONL line format is a shared contract between `foundation_tools.jsonlog` and
  `hooks/_lib.py`; tests keep the two emitters field-compatible since the code is
  intentionally not shared across the dependency boundary.
