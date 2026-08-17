# 0034 - Ruff/mypy pins stay hand-duplicated, and are drift-tested rather than templated

**Status**: Accepted — lands with `openspec/changes/pin-lockstep-tool-versions/` as F-055
(`implemented_in` recorded in `features.yaml`). Enforcement is live from the same change:
`scripts/validations/F_055.py` runs in the tier-fast validation set from the commit that
flips F-055 to `done`.
**Date**: 2026-08-17

Related: [ADR 0009](0009-tech-debt-audit-and-compat-surface.md) (the tech-debt baseline this
change does not regress), [ADR 0021](0021-ci-gate-delegation.md) (CI gate delegation — the
precedent this change deliberately does *not* extend to `skills-ci.yml`'s pip-install
lines), `AGENTS.md` "Non-negotiable constraints" (the pin bullet this ADR is now cited from),
`docs/plans/orbital-drift-alignment/PLAN.md` Phase 2 (the plan this change implements).

## Context and Problem Statement

`ruff==0.15.20` and `mypy==2.1.0` are pinned, not floored, in the `dev` extra of every
package's `pyproject.toml` so that local and CI lint/format/type-check runs agree byte for
byte — an unpinned ruff drifted once already (0.8.0 local vs 0.15.20 CI) and broke
`ruff format --check` (`pyproject.toml:81-83`). That reproducibility requirement means the
same two version strings are hand-typed in eight separate places: the `dev` extra of 7
`pyproject.toml` files (root, `agent-core`, `behavioral-regression`, `flow-protocol`,
`flow-corpus`, `claude-foundation`, `experiments/backend-validation`) and every `pip install`
line across `.github/workflows/skills-ci.yml`'s per-skill CI jobs — 16 hand-typed copies in
total. Each copy carries a "bump deliberately, in lockstep" comment (e.g.
`agent-core/pyproject.toml:31-33`, `claude-foundation/pyproject.toml:34-35`), but before this
change nothing checked that the comment's promise held. A partial bump — one file edited,
fifteen forgotten — would silently drift: green in whichever job happened to install the
updated pin, red (or, worse, silently different) wherever an old copy still installed.
No test existed anywhere in the repo to catch this, despite it being exactly the "green
locally, red in CI" failure mode a lockstep test exists to prevent.

The question is not whether to keep the pins reproducible — `AGENTS.md`'s "do not bump them
casually" framing (the line this ADR is now cited from) already settled that. The question is
how sixteen call sites stay honest without turning a two-line reproducibility fix into a
sixteen-file refactor.

**Known, separately-tracked surface, not covered by the eight-file census above:**
`agent-core/.pre-commit-config.yaml`'s `ruff-pre-commit rev:` was found, during this change's
review, still pinned at `v0.8.0` — live, contributor-facing, and the exact version this
Context section's own "drifted once already" sentence describes. Bumped to `v0.15.20` in the
same change that lands this ADR, but `F_055.py` (formerly drafted as F-054; renumbered — see
Compliance) does not check it: pre-commit `rev:` pins use different YAML shape than the
`tool==version` string the regex matches, and this repo's `dev`-extra/`skills-ci.yml` set is
already sixteen call sites without adding a seventeenth to the same script. A dedicated,
small companion check (or folding pre-commit `rev:` pins into a future version of this one)
is the honest way to close that gap — tracked as a fast-follow, not silently left unmentioned.

## Decision

Keep the duplication; test the lockstep instead of removing it.

1. **One canonical source, in code, not policy.** `scripts/tool_versions.py` defines
   `RUFF_VERSION`/`MYPY_VERSION` as the two literal strings every other copy must match. It
   installs nothing and runs nothing — it only names the values, the same role
   `scripts/eval_protected_paths.py` plays for the protected-path set.
2. **A read-only gate, not a rewrite.** `scripts/validations/F_055.py` reads the text of the
   7 `pyproject.toml` files and `.github/workflows/skills-ci.yml`, and asserts every
   `ruff==`/`mypy==` occurrence in them equals `tool_versions.py`'s constants exactly — and
   that no copy has silently lost its pin. It performs no installs, no subprocess calls, and
   no edits; `skills-ci.yml` in particular is deliberately read-only in this change, because a
   sibling phase in `docs/plans/orbital-drift-alignment/PLAN.md` (Phase 3) edits that same
   file, and Phase 0's file-collision map resolves the overlap by construction: this change
   only ever reads it.
3. **Casual bumping stays exactly as hard as it was.** This gate tests *drift* — sixteen
   copies disagreeing with each other — not the act of bumping itself. A deliberate version
   bump still requires editing `tool_versions.py` and propagating the same two values by hand
   to every `pyproject.toml` dev extra and every `skills-ci.yml` install line; F-055 simply
   makes "propagating by hand, correctly, everywhere" a CI-checked fact instead of a comment's
   unverified promise. `AGENTS.md`'s "do not bump them casually" constraint is respected, not
   relaxed — a bump is still sixteen hand-edits and still a reviewed diff; the only change is
   that a *partial* one now fails the build instead of merging silently.
4. **Full CI templating is deferred, not rejected.** Interpolating `pyproject.toml`'s `dev`
   extra directly into all `skills-ci.yml` install lines at workflow-run time — so the
   version strings are typed exactly once and every consumer reads them, rather than sixteen
   hand-synced literals — was considered. It is explicitly deferred as a separate, larger
   follow-on: it touches every per-skill CI job definition (each currently a plain `pip install` shell
   line) for marginal gain over what this change already delivers. "Drift cannot merge
   silently" is the actual guarantee sought, and F-055 delivers it today at a fraction of the
   surface area; templating would trade a tested duplication for an untested indirection layer
   across every skill job, which is not a strict improvement and is exactly the kind of
   larger, separately-reviewable change ADR 0021's own CI-delegation precedent suggests should
   land on its own.

## Consequences

**Positive.** A partial ruff/mypy bump — one file updated, others forgotten — now fails
`scripts/validate.py --tier fast` (wired into CI via `quality-gates.yml`) with a message
naming the exact file and the mismatched version found, instead of merging silently and
surfacing later as an unreproducible CI failure. The fix required one new 25-line constants
module and one new read-only validator; no existing file's install/lint/type-check behaviour
changed.

**Positive.** The gate also catches a pin being dropped entirely (loosened to `ruff>=`, or
deleted outright) in any of the 8 files, not only a wrong version — the same "vacuity is
refused" discipline `ADR 0032`'s matrix census applies to an empty component list applies
here to an empty pin.

**Negative.** Sixteen hand-typed copies still exist, and a deliberate bump is still sixteen
edits (`tool_versions.py` plus every `pyproject.toml` dev extra plus every `skills-ci.yml`
line) rather than one. The gate proves the copies agree; it does not reduce how many places a
correct bump must touch. This is the trade this ADR makes deliberately (§4 above) — templating
would reduce edit count at the cost of touching every per-skill CI job definition and introducing a
runtime interpolation seam that does not exist today.

**Neutral.** `scripts/validations/F_055.py` follows `scripts/validations/F_031.py`'s existing
shape (same `_common.check`/`report`/`configure_logging` helpers, same read-only,
deterministic, offline design, same exit-code contract) rather than introducing a new
validator pattern. `scripts/tool_versions.py` carries no logger — it is a plain constants
module with no runtime branching to diagnose, the same choice `scripts/eval_protected_paths.py`
makes for the protected-path set it single-sources.

## Compliance

Enforced by `scripts/validations/F_055.py`, which runs in the tier-fast validation set via
`features.yaml`'s F-055 `validation_command`; `python scripts/validate.py --tier fast`
discovers and executes it, and `.github/workflows/quality-gates.yml` runs
`python scripts/validate.py --tier fast --strict` on every PR. A deliberate mismatch
introduced in any of the 8 covered files reproduces a targeted, file-and-version-naming
failure (verified manually against `agent-core/pyproject.toml` at introduction; see
`openspec/changes/pin-lockstep-tool-versions/tasks.md` "Verification").
