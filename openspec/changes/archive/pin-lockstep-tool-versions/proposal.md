# Change: pin-lockstep-tool-versions

**Status:** implemented · **Date:** 2026-08-17 · **Author track:** `claude/` agent lane
**Motivated by:** `docs/plans/orbital-drift-alignment/PLAN.md` Phase 2, itself motivated by a
file-by-file comparison against a sibling project's CI discipline, independently
fact-checked against this repo's actual files (not trusted from the comparison).
**Compiles down to:** `scripts/tool_versions.py` (source of truth) + F-055
(`features.yaml`, `scripts/validations/F_055.py`) + [ADR 0034](../../../docs/decisions/0034-tool-version-lockstep.md).

## Why

`ruff==0.15.20` and `mypy==2.1.0` are pinned, not floored, so local and CI lint/format/
type-check runs agree byte for byte — the root `pyproject.toml`'s own comment records that
an unpinned ruff drifted once already (0.8.0 local vs 0.15.20 CI) and broke
`ruff format --check` (`pyproject.toml:81-83`).

That reproducibility requirement is currently satisfied by hand-typing the same two version
strings in **16 separate places**, each verified directly against the tree at proposal time:

| # | File | Line(s) | Pin |
|---|---|---|---|
| 1 | `pyproject.toml` (root) | 84 | `"mypy==2.1.0", "ruff==0.15.20"` |
| 2 | `agent-core/pyproject.toml` | 34 | `"ruff==0.15.20", "mypy==2.1.0"` |
| 3 | `behavioral-regression/pyproject.toml` | 36 | `"ruff==0.15.20", "mypy==2.1.0"` |
| 4 | `flow-protocol/pyproject.toml` | 35 | `"ruff==0.15.20", "mypy==2.1.0"` |
| 5 | `flow-corpus/pyproject.toml` | 35 | `"ruff==0.15.20", "mypy==2.1.0"` |
| 6 | `claude-foundation/pyproject.toml` | 36 | `"mypy==2.1.0", "ruff==0.15.20"` |
| 7 | `experiments/backend-validation/pyproject.toml` | 38-39 | `"mypy==2.1.0",` / `"ruff==0.15.20",` (multi-line) |
| 8-16 | `.github/workflows/skills-ci.yml` | 48, 82, 117, 151, 183, 211, 239, 265, 294 | `"ruff==0.15.20" "mypy==2.1.0"` (9 per-skill jobs) |

Six of the seven `pyproject.toml` copies carry a "bump deliberately, in lockstep" comment
(e.g. `agent-core/pyproject.toml:31-33`: *"ruff/mypy are pinned (not `>=`) so local and CI
lint/type identically across every workspace member ... Bump deliberately, in lockstep with
the root dev extra."*) — a promise about sixteen call sites with **no automated check**
anywhere in the repo that they actually agree. A partial bump (one file edited, fifteen
forgotten) is exactly the "green locally, red in CI" failure mode a lockstep test exists to
prevent, and this is the same manual-list-vs-derived-reality defect class this repo has
already closed twice for other invariants — F-050 derived the skills-CI job list from the
directory tree instead of a hand-maintained allowlist, and F-052 derived protected-path CI
reachability from the guard's own pattern list instead of trusting a second, hand-synced
copy. This proposal closes the same defect class for the ruff/mypy pins.

## What changes

- Add `scripts/tool_versions.py`: `RUFF_VERSION`/`MYPY_VERSION`, the one place a version is
  typed. No installs, no subprocess calls — it only names the values.
- Add `scripts/validations/F_055.py`: a **read-only** text check (opens each file for
  reading only; runs no subprocess and no code execution) over the 7 `pyproject.toml` files
  and `.github/workflows/skills-ci.yml`, asserting every `ruff==`/`mypy==` occurrence matches
  `tool_versions.py`'s constants exactly, and that no file has silently lost its pin
  entirely. Structured after `scripts/validations/F_031.py` — same `_common.check`/`report`/
  `configure_logging` helpers, same read-only/deterministic/offline shape, same exit-code
  contract — deliberately the same pattern, not a new one.
- Claim F-055 in `features.yaml`.
- Point `AGENTS.md`'s existing pin bullet (`AGENTS.md:97`) at `scripts/tool_versions.py` as
  the canonical source, one line, no restructuring of the surrounding doc.
- Add [ADR 0034](../../../docs/decisions/0034-tool-version-lockstep.md), documenting
  "drift-tested duplication, not full templating."

## Scope / non-goals

- **Non-goal: editing `.github/workflows/skills-ci.yml`.** This proposal is deliberately
  read-only on that file. `docs/plans/orbital-drift-alignment/PLAN.md` Phase 0 §1 resolves a
  soft overlap with a sibling phase (`test-skill-validator-library`, which edits
  `skills-ci.yml` to add a job and remove an `EXEMPT` entry) by construction: this change
  only ever reads it, so the two phases cannot collide regardless of merge order.
- **Non-goal: full CI templating.** Interpolating `pyproject.toml`'s `dev` extra into all 9
  `skills-ci.yml` install lines at workflow-run time — so the version strings are typed once
  and every consumer reads them — was considered and is explicitly deferred (ADR 0034 §4) as
  a separate, larger follow-on: it touches 9 CI job definitions for marginal gain over what
  this change already delivers (drift cannot merge silently).
- **Non-goal: relaxing the "bump deliberately" constraint.** `AGENTS.md`'s "do not bump them
  casually" framing is the constraint this change respects, not loosens. F-055 tests *drift*
  between the 16 copies; a deliberate, correct bump made everywhere still requires the same
  16 hand-edits it always did, and remains a reviewed diff.
- **Non-goal: a new validator pattern.** F_055.py's shape (helpers, exit codes, reporting) is
  copied from F_031.py on purpose; no new validation idiom is introduced.

## Impact

- New, additive files only: `scripts/tool_versions.py`, `scripts/validations/F_055.py`. No
  existing lint/format/type-check/install behaviour changes for any package or skill job.
- **Protected paths:** `features.yaml`, `scripts/validations/**` — this implementation
  carries the `eval-change-approved` label per `scripts/eval_protected_paths.py`.
  `.github/**` is also protected; this change touches it only by reading
  `.github/workflows/skills-ci.yml` from `F_055.py` at validation time, never by editing it.
