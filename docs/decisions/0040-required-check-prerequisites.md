# 0040 - Prerequisites for required status checks: namespaced check contexts and stub jobs

**Status**: Accepted — unlike [ADR 0037](0037-branch-protection-under-a-single-maintainer.md),
everything here ships as repository content and is verifiable from the repository itself.
**Date**: 2026-09-04

Related: [ADR 0037](0037-branch-protection-under-a-single-maintainer.md) (which proposes
enabling required status checks on `main`; this ADR removes three defects that would have
made that change actively harmful), [ADR 0028](0028-claude-foundation-staging.md),
[ADR 0034](0034-tool-version-lockstep.md), `scripts/check_guard_reachability.py`.

## Context and Problem Statement

ADR 0037 nominates a set of checks to require on `main`. Enabling them against the CI as it
stood would have produced three failures, all of them silent:

1. **Colliding check contexts.** `eval-harness-ci.yml`, `agent-core-ci.yml` and
   `claude-foundation-ci.yml` each declared the bare job name `py${{ matrix.python-version }}`,
   so all three published the identical contexts `py3.11`/`py3.12`/`py3.13`. Branch
   protection matches a required check by context *string*. A pull request touching only
   `claude-foundation/` produced a green `py3.12` that would have satisfied a requirement
   meant for the eval-harness suite — a suite that never ran. Two workflows
   (`behavioral-regression-ci.yml`, `flow-corpus-ci.yml`) already namespaced their matrix
   jobs; the other three did not.
2. **No reported check for a filtered-out workflow.** A workflow skipped by its `paths:`
   filter creates no check run at all, and a required check with no run sits in
   "Expected — waiting for status to be reported" indefinitely. ADR 0037 deliberately does
   not enable Code-Owner review, so there is no review-bypass path: a docs-only,
   `skills/`-only, `Makefile`-only or `AGENTS.md`-only pull request would have become
   permanently unmergeable.
3. **A missing dependency edge.** `src/eval_harness` imports `agent_core` at 58 sites, and
   `eval-harness-ci.yml` installs `./agent-core` before running its gate — yet `agent-core/**`
   appeared in neither that workflow's `paths:` filter nor `quality-gates.yml`'s (which
   listed only `agent-core/tests/**`, for protected-path reasons). A signature change to,
   say, `wilson_interval` could merge green and break `main`.

## Decision

1. **Every check context is namespaced by the suite that produces it.** `eval-harness py3.x`,
   `agent-core py3.x`, `claude-foundation py3.x`, matching the two workflows that already did
   this. No workflow may publish a context that does not name its own suite.
2. **Every required-check candidate has a companion stub job that reports the same context
   and exits 0**, in a single workflow, `.github/workflows/required-check-stubs.yml`.
3. **The stub gate derives its condition from the real workflows, rather than mirroring
   them.** The textbook stub pattern is a companion workflow whose `paths-ignore:` repeats
   the real workflow's `paths:`. That is rejected here for two reasons:
   - `paths:` and `paths-ignore:` are **not complements**. GitHub runs a `paths:` workflow
     when at least one changed file matches, and a `paths-ignore:` workflow when at least one
     changed file does *not* match. A pull request touching `src/` **and** `docs/` triggers
     both — which describes most pull requests in this repository. The stub would post a
     green `eval-harness py3.12` beside the real one, re-creating the duplicate-context
     false green that decision 1 exists to remove.
   - A mirrored list is a second copy of the filter, and a drift between the two re-opens
     the hole it was written to close.

   Instead, one `gate` job reads each real workflow's own `on.pull_request.paths:` block out
   of the workflow file and evaluates it against the pull request's changed files (listed via
   the pull-requests read API, including `previous_filename` so a rename counts as touching
   both paths). Each stub job runs if and only if its real workflow did not. There is exactly
   one path list per workflow — the real one.
4. **The stub gate fails closed.** An unreadable or empty `paths:` block is an error, not an
   empty list. If the gate fails, its dependent stubs are skipped and the required contexts
   stay unreported: a loud red gate that blocks a merge is recoverable, a silent green stub
   standing in for a suite nobody ran is not.
5. **`agent-core/**` is a path filter of `eval-harness-ci.yml` and `quality-gates.yml`**, on
   both `push` and `pull_request`. In `quality-gates.yml` it sits alongside — not instead of
   — `agent-core/tests/**`: that entry exists for the protected-path guard's reachability
   (`scripts/check_guard_reachability.py`), this one for the build dependency, and the two
   have independent reasons to exist.
6. **Dependency updates are automated with Dependabot** (`.github/dependabot.yml`): pip for
   the root package and all five sibling directories, plus github-actions, monthly and
   grouped so a single-maintainer repository is not handed dozens of pull requests. `ruff`
   and `mypy` are excluded: they are pinned in lockstep across the fleet (ADR 0034,
   `scripts/validations/F_055.py`), so a per-directory bump fails CI by construction.

## Consequences

- **Positive.** The required-check set ADR 0037 names can now be enabled without either a
  false green (decision 1) or a permanently unmergeable docs-only pull request (decision 2).
- **Positive.** An `agent-core`-only pull request now re-runs the eval-harness suite that
  depends on it, which is what `eval-harness-ci.yml`'s own install step always implied.
- **Negative, now mitigated.** The stub workflow's job list is a contract: a real job's
  `name:` renamed without renaming its stub leaves the required context unreported on
  filtered-out pull requests. The file says so at the top, but a note is not a gate, so
  `tests/test_required_check_stubs.py` now derives both sides from the workflow files and
  asserts they match in both directions — missing stubs *and* orphan stubs. Verified by
  mutation: renaming a real job with its stub untouched fails with both sets named.
- **Negative.** One extra small job (`required-check stub gate`) runs on every pull request.
  That is the price of deciding the stub condition from live data instead of a mirrored list.
- **Neutral, and confirmed against a live run rather than predicted.** On a pull request that
  straddles a filter, the real workflow runs and its stub is skipped by a job-level `if:`.
  GitHub reports a skipped job as a check run, and for a **matrix** stub it does *not* expand
  the matrix before skipping — the run is posted under the literal name
  `eval-harness py${{ matrix.python-version }}`. Observed on this ADR's own pull request
  (`a9b2d65`), where the `eval-harness`, `agent-core`, `claude-foundation`, quality-gates and
  architecture-drift stubs were skipped while their real workflows ran, and the
  `flow-corpus`, `flow-protocol` and `behavioral-regression` stubs ran and posted correctly
  expanded names.

  Two consequences follow, and the first is the one that matters. A skipped matrix stub
  therefore posts a context that **no required check can ever name**, so it can never satisfy
  a requirement on the real job's behalf — the duplicate-context hazard decision 1 exists to
  remove does not arise here. The cost is cosmetic: a handful of unexpanded placeholder rows
  in the checks list on pull requests that trigger a matrix workflow. Left as-is deliberately.
  Suppressing them means driving the matrix itself from `fromJSON(...)` so it evaluates to an
  empty list, which trades a proven mechanism for an exotic one to remove noise that misleads
  nobody. Revisit only if the noise becomes a real review burden.
