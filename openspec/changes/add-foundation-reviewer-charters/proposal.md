# Change: add-foundation-reviewer-charters

**Status:** proposed · **Date:** 2026-08-17 · **Author track:** `claude/` agent lane
**Motivated by:** `docs/plans/orbital-drift-alignment/PLAN.md` Phase 4, itself grounded in a
verified gap, not an assumed one: `claude-foundation/agents/` holds exactly two files today
(`explorer.md`, `test-runner.md`), no spec-guardian/peer-reviewer-equivalent charter exists,
and no sequential blocking review-loop convention exists anywhere in this repo to slot one
into. Review discipline today is CI-mechanical gates (`scripts/validate.py`,
`quality-gates.yml`), protected-path CODEOWNER+label gates (`scripts/eval_protected_paths.py`,
`.github/CODEOWNERS`), and a single-pass, forked, read-only `foundation:code-review` skill
whose own frontmatter says it "Returns severity-ranked findings with file:line and a
blocking/non-blocking/clean verdict" — one pass, one reviewer, no fact-check/adversarial
split and no dedicated spec-conformance step. This is net-new capability, not a gap-fill
(Decision Point 1, same PLAN.md).
**Compiles down to:** two new `claude-foundation/agents/*.md` charters plus an
`openspec/AGENTS.md` fleet-contract update. No ADR and no `features.yaml` F-ID — Phase 4's
own table lists neither; this is agent registration under `claude-foundation/CLAUDE.md`'s
existing append-only compat contract, not a new architectural decision or a capability the
root spec system tracks.

## Why

Every review mechanism this repo has today is either purely mechanical (a script that either
passes or fails, no judgment involved) or single-pass (`foundation:code-review`: one fork,
one checklist, one verdict line, done). Nothing plays back a change against its *own*
declared spec/plan/decision surface before a human or a peer-review pass sees it, and nothing
in the fleet does the two-pass fact-check-then-adversarial-attack method this repo's own
`review.md` artifacts already use by hand — see `openspec/changes/add-panel-judge/review.md`
and `docs/plans/orbital-drift-alignment/PLAN.md`'s own "Objective peer-review step", which
today can only say *"performed by a `general-purpose` subagent dispatch (the reviewer
charters don't exist yet...)"* for Phases 1-4. That sentence is the gap this change closes:
after it lands, "the reviewer charters don't exist yet" stops being true.

## What changes

- Add `claude-foundation/agents/spec-guardian.md` — a read-only conformance reviewer.
  Checks a change's implementation against its own declared spec/plan/decision surface and
  flags protected-path discipline gaps, reporting `Verdict: conforms` / `Verdict: drift`
  plus numbered `file:line` findings. Discovers the *current* repo's own planning/decision
  conventions at invocation time rather than assuming this repo's layout — see `design.md`.
- Add `claude-foundation/agents/peer-reviewer.md` — a read-only adversarial reviewer.
  Two passes: pass 1 mechanically fact-checks every falsifiable claim in the target
  (CONFIRMED / CORRECTED / REFUTED, each with evidence); pass 2, labeled and reported
  separately, actively tries to break the design or implementation, keeping refuted attacks
  in the output rather than deleting them. Same portability contract as `spec-guardian`.
- Update `openspec/AGENTS.md`: two new lifecycle-table rows (`review`, conformance pass and
  adversarial pass) between `verify` and `archive`; correct the closing claim "nothing here
  invents a new agent," which this phase makes false, with a stated exception naming the
  native role each new charter fills; add the previously-unstated staging precondition
  (`claude --plugin-dir claude-foundation`, ADR 0028) that every `claude-foundation`-sourced
  fleet row — old and new — actually requires.
- Register both charters per `claude-foundation/CLAUDE.md`'s existing convention:
  `README.md` Components table (+2 rows), `CHANGELOG.md` `[Unreleased]` entry,
  `tests/backwards_compat_baseline.json` regenerated via `--update` (pure addition).
- Dogfood: apply both charters' stated procedure, in character, to a real change, producing
  a genuine `review.md` — the functional proof PARITY-with-precedent calls for instead of a
  scripted eval suite (Decision Point 1). See "Scope / non-goals" and `design.md` for why
  this step is reported as blocked rather than fabricated from this worktree.

## Scope / non-goals

- **Non-goal: a scripted eval suite.** Decision Point 1 (PLAN.md) sets PARITY with
  `explorer`/`test-runner`, neither of which has one. Structural validation
  (`foundation_tools.validate`, `.scan`, `.backwards_compat`, `claude plugin validate`) plus
  a dogfooded review is the proof this round; a higher bar would be a new precedent, not a
  gap-fill, and is explicitly out of scope here.
- **Non-goal: a mandatory or CI-blocking review gate.** Decision Point 2 (advisory/opt-in)
  belongs to Phase 5 (`add-openspec-implementation-review`), which depends on this change and
  is not part of it. Nothing here touches `CONTRIBUTING.md`, `GOVERNANCE.md`, protected
  paths, or CI.
- **Non-goal: the dispatch/orchestration skill.** Phase 5 builds the skill that locates an
  OpenSpec change, dispatches these charters (or degrades gracefully without
  `claude-foundation` plugin-loaded), and composes `review.md`. This change ships the two
  charters that skill will call; it does not build the caller.
- **Non-goal: an ADR.** Two agent charters registered under an existing, already-decided
  compat contract are not a new architectural decision; `docs/decisions/` gains nothing here
  (contrast Phase 2, which does add one).
- **Non-goal: extracting `claude-foundation` from staging.** ADR 0028 is unaffected; both
  charters are authored and validated in the staging tree like every existing component.
- **Non-goal: retroactive `review.md` backfill for Phases 1-3.** PLAN.md's Phase 5 section
  calls that a deliberate follow-on once Phase 5 exists, not part of Phase 4.

## A correction to the plan this change implements

`docs/plans/orbital-drift-alignment/PLAN.md`'s Phase 4 table marks the "Registration" row
`Protected: no`. That is incorrect for one of its three files:
`claude-foundation/tests/backwards_compat_baseline.json` matches
`scripts/eval_protected_paths.py`'s `claude-foundation/tests/**` pattern, is listed in
`.github/CODEOWNERS` (`/claude-foundation/tests/ @ianshank`), and sits inside the
`pull_request` path filter that re-runs the protected-path guard in
`.github/workflows/quality-gates.yml`. The regeneration is still a pure, append-only,
never-fails-CI addition exactly as the plan says — but the file is protected by path,
regardless of how harmless its diff is, so the PR that lands this change needs the
`eval-change-approved` label and `@ianshank`'s review on that one file. `README.md`,
`CHANGELOG.md`, and both new `agents/*.md` files are not protected by any pattern in
`scripts/eval_protected_paths.py`.

## Impact

- Purely additive agent surface: `claude-foundation/agents/spec-guardian.md` and
  `.../peer-reviewer.md`. No engine, runtime, or Python source changes; no `SCHEMA_VERSION`
  or plugin major-version implications (`recorded_major_version` stays `1`).
- `openspec/README.md` gains a "Current changes" entry for this package — mechanically
  required by the OpenSpec change-index guard in `.github/workflows/docs.yml`.
- No `features.yaml` row, no `scripts/validations/F_0NN.py` proof — Phase 4 claims neither.
