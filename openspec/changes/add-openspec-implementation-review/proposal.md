# Change: add-openspec-implementation-review

**Status:** proposed · **Date:** 2026-08-17 · **Author track:** `claude/` agent lane
**Motivated by:** `docs/plans/orbital-drift-alignment/PLAN.md` Phase 5, which depends on
Phase 4 (`add-foundation-reviewer-charters`, merged). `openspec/AGENTS.md`'s lifecycle table
already names a `review` phase owned by `spec-guardian`/`peer-reviewer`, but nothing locates a
change, decides whether those charters are actually dispatchable, composes the prompt(s) to
send, or assembles the result into `openspec/changes/<id>/review.md` — the fleet contract
describes the destination without a path to it. `openspec/AGENTS.md`'s own staging-precondition
paragraph states the requirement this change exists to satisfy: "Phase 5 ... is required to do
exactly this [degrade to a `general-purpose` subagent] for `review` rather than silently
failing to find the agents."
**Compiles down to:** a new skill (`skills/openspec-implementation-review/`), registered in
`skills/marketplace.yaml` and given a dedicated `skills-ci.yml` job; no ADR (agent registration
under an existing, already-decided compat contract, same reasoning `add-foundation-reviewer-
charters` gave for skipping one); no `features.yaml` F-ID (skill registration, not a harness
capability — no skill in this repo's history carries one for its own registration).

## Why

Two facts, both independently confirmed rather than assumed, define this change's actual
shape:

1. **`claude-foundation` is staged, not loaded, in this repo's own sessions (ADR 0028).**
   `add-foundation-reviewer-charters`'s own `tasks.md` §4 records that the orchestrating
   session which merged Phase 4 checked its own available subagent types and found
   `spec-guardian`/`peer-reviewer` absent — only generic types (`general-purpose`, `Explore`,
   `Plan`, ...) are available without a session actually started with `claude --plugin-dir
   claude-foundation`. This is not a rare edge case this skill defends against defensively; it
   is the **normal, expected state** of every session working this repo directly today.
2. **Nothing can dispatch a subagent from inside a Python script.** `spec-guardian`,
   `peer-reviewer`, and `general-purpose` are tools of the calling agent's own harness — a
   `scripts/implreview/*.py` module cannot invoke any of them, any more than
   `skills/quality-gate`'s generator can invoke `pytest` on your behalf without you running the
   script it wrote. This bounds what this skill's *code* can do: locate the change, produce the
   *evidence* for which dispatch path looks available, compose the exact prompt(s), and
   assemble the result — never the dispatch itself.

Given both, the honest design is a skill that treats the degraded path as the one that actually
runs — not a rare fallback bolted on after the "real" plugin path — while still producing an
identical output shape either way, so a `review.md` produced today (degraded) and one produced
after `claude-foundation`'s eventual extraction (ADR 0028 M7, plugin-loaded) are
indistinguishable in structure.

## What changes

- Add `skills/openspec-implementation-review/`, a full artifact-producing skill (`SKILL.md`,
  `scripts/implreview/` + `scripts/run.py`, vendored `scripts/validate_skill.py`, `tests/`,
  `evals/evals.json` with ≥3 cases) that:
  - **Locates** an OpenSpec change by explicit id, or infers one from the current git branch
    name / recent commit subjects, and confirms `tasks.md` looks complete before proceeding.
  - **Detects** whether the plugin dispatch path looks available via a real, narrow,
    filesystem-checkable signal (`CLAUDE_PLUGIN_ROOT` resolving to this repo's
    `claude-foundation/` staging directory) — conservative by construction: it recommends
    `plugin` only when that signal is actually present, and states plainly that the signal is
    necessary, not sufficient, so the calling agent must still corroborate against its own
    actual subagent-type list before dispatching by name.
  - **Composes** the dispatch prompt(s): `spec-guardian` then `peer-reviewer` for the plugin
    path, or one fully self-contained `general-purpose` prompt with the entire two-pass method
    inlined for the degraded path — written to need nothing beyond itself, since it is the path
    this repo's sessions actually exercise.
  - **Assembles** `openspec/changes/<id>/review.md` from a dispatched reviewer's output,
    creating it fresh or — decided, not left ambiguous — appending a new, separately dated
    `## Follow-up review — <date>` section if one already exists, never silently overwriting.
- Register the skill in `skills/marketplace.yaml` and give it a dedicated job in
  `.github/workflows/skills-ci.yml` (real library code, ADR 0030's full-tier class — confirmed
  by running the `all-skills` job's own reconciliation script locally: no `EXEMPT` entry needed
  once the job is registered under the exact skill-directory name).
- Add this package's entry to `openspec/README.md`'s "Current changes" — mechanically required
  by the OpenSpec change-index guard in `.github/workflows/docs.yml`.

## Scope / non-goals

- **Non-goal: a CI gate.** Decision Point 2 (`PLAN.md`) is advisory/opt-in. This skill is not
  wired into `CONTRIBUTING.md`, `GOVERNANCE.md`, protected paths, or any CI job as mandatory —
  a contributor or agent invokes it on demand, exactly like `openspec-peer-review` today.
- **Non-goal: duplicating `openspec-peer-review`.** That skill reviews a *plan* package before
  implementation starts and rewrites it. This skill reviews a *landed implementation* against
  its own plan and never rewrites anything — a different lifecycle phase, a different output
  (a persistent `review.md`, not a plan revision), and a deliberately different name so the two
  are never confused in a directory listing.
- **Non-goal: dispatching a real subagent from CI or from this package's own tests.** Neither
  environment can do that (see "Why"). Tests exercise the locate/detect/compose/validate logic
  directly, using fixture-based fake `openspec/changes/<fixture-id>/` trees for anything that
  would otherwise need a live dispatch; the degraded path's own prompt composition and the
  `review.md` structural validator are both exercised end-to-end via real subprocess calls in
  `evals/evals.json`, including a real two-pass create-then-append round trip.
- **Non-goal: claiming the plugin path was tested end-to-end.** It cannot be, from this
  environment — confirmed, not assumed (see "Why," point 1). `tests/test_detect.py` asserts
  the plugin-path *logic* against fixture directories (a real code path, genuinely exercised)
  and separately asserts, against the *real* repository tree with no environment override, that
  detection lands on `degraded` today — the one true-positive-shaped claim this environment can
  actually support.
- **Non-goal: retroactively backfilling `review.md` for Phases 1–3.** `PLAN.md`'s own
  Bootstrapping note calls this a follow-on once this skill exists, not part of landing it.
- **Non-goal: an ADR or a `features.yaml` F-ID.** Same reasoning `add-foundation-reviewer-
  charters` gave for neither: this is skill registration under `docs/SKILL_TEMPLATE.md`'s
  already-decided contract, not a new architectural decision or a harness capability this
  repo's F-ID system tracks (no skill's own registration carries one).

## Impact

- Purely additive: one new skill directory, one `marketplace.yaml` entry, one new
  `skills-ci.yml` job, one `openspec/README.md` bullet, one new `TRACKED_DUPLICATES` entry in
  `scripts/check_skill_script_drift.py`. No engine, runtime, or Python source outside
  `skills/openspec-implementation-review/` changes.
- No protected-path source is edited by the skill's own runtime code; the CI/marketplace/
  drift-guard wiring above touches `.github/**` (CODEOWNERS-protected), so the PR that lands
  this change needs the `eval-change-approved` label and review, matching every prior phase's
  own CI-wiring edits.
- `python scripts/skill_marketplace.py validate`, `python scripts/check_skill_script_drift.py`,
  and the `all-skills` job's own reconciliation logic all pass against the landed tree — run
  directly, not assumed (see `tasks.md` §Verification).
