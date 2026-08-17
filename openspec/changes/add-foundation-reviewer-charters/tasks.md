# Tasks: add-foundation-reviewer-charters

`[P]` = protected path; needs the `eval-change-approved` label + CODEOWNERS review before
merge (`scripts/eval_protected_paths.py`). No coverage floor applies to this change — it
touches no Python source, only agent markdown, docs, and one regenerated JSON fixture.

## 1. Charters

- [x] `claude-foundation/agents/spec-guardian.md` — frontmatter is exactly `name,
      description, tools, model, maxTurns`, in that order; `name: spec-guardian` byte-matches
      the filename stem; `tools: Read, Grep, Glob` (no Bash); `model: sonnet`; `maxTurns: 30`.
- [x] `claude-foundation/agents/peer-reviewer.md` — same frontmatter shape; `name:
      peer-reviewer` byte-matches the filename stem; `tools: Read, Grep, Glob`; `model:
      opus`; `maxTurns: 40`.
- [x] Both bodies: 1-2 sentence identity ("You are a(n) X agent. Your job is to Y — never
      to Z.") + exactly one `## Rules` heading + 6 numbered imperative rules; zero
      repo-specific paths (matches `explorer.md`/`test-runner.md`'s portability property).
- [x] Both Rules sections specify the dynamic-discovery order verbatim from
      `docs/plans/orbital-drift-alignment/PLAN.md` Phase 4: `CLAUDE.md`, `AGENTS.md`,
      `openspec/`, `docs/decisions/`, `specs/`, `.specify/`, whichever actually exist;
      state explicitly when none do, rather than failing silently or inventing one.
- [x] `spec-guardian.md` reports `Verdict: conforms` / `Verdict: drift` first, then numbered
      `file:line` findings; checks protected-path discipline when a definition is
      discoverable, without assuming discipline was followed absent visible evidence.
- [x] `peer-reviewer.md` specifies the two-pass method: pass 1 gives every falsifiable claim
      exactly one verdict (CONFIRMED / CORRECTED / REFUTED) with a `file:line` citation;
      pass 2 is separately labeled and adversarial, verifying each attack before keeping it,
      with refuted attacks kept in the output rather than deleted.

## 2. Fleet contract

- [x] `openspec/AGENTS.md` — two new lifecycle-table rows, `review` (conformance pass,
      owner `spec-guardian`) and `review` (adversarial pass, owner `peer-reviewer`), placed
      between `verify` and `archive`; gate column reads "advisory — a `tasks.md` checklist
      item, never CI-blocking" (Decision Point 2 stays Phase 5's to spend, not spent here).
- [x] Corrected the closing claim "nothing here invents a new agent" (no longer true): the
      intro now states the exception by name and the native role each new charter fills.
- [x] Added the staging precondition (`claude --plugin-dir claude-foundation`, ADR 0028) as
      a stated fact — it covers every `claude-foundation`-sourced fleet row, including the
      three pre-existing `foundation:*` skill rows and `test-runner`, which had none before.

## 3. Registration

- [x] `claude-foundation/README.md` Components table: two new `Subagent` rows, same column
      shape as the `explorer`/`test-runner` rows.
- [x] `claude-foundation/CHANGELOG.md` `[Unreleased] > Added`: one entry covering both
      charters, their portability contract, and the parity-not-gap eval-rigor rationale
      (Decision Point 1).
- [x] `[P]` `claude-foundation/tests/backwards_compat_baseline.json` regenerated via
      `python -m foundation_tools.backwards_compat --root . --update` (run from
      `claude-foundation/`, the invocation `CLAUDE.md`'s Build/Test Commands documents).
      Before: `added: {"agents": ["peer-reviewer", "spec-guardian"]}`, `removed: {}`. After:
      `added: {}`, `removed: {}` — a pure, append-only addition; `recorded_major_version`
      stays `1`. **Marked `[P]` as a correction to
      `docs/plans/orbital-drift-alignment/PLAN.md` Phase 4's table, which marks this row
      "Protected: no."** The file matches `scripts/eval_protected_paths.py`'s
      `claude-foundation/tests/**` pattern, is listed in `.github/CODEOWNERS`
      (`/claude-foundation/tests/ @ianshank`), and sits inside the `pull_request` path
      filter that re-triggers the protected-path guard in
      `.github/workflows/quality-gates.yml` — the eventual PR needs the label and that
      review regardless of how harmless the diff is. See `proposal.md`, "A correction to
      the plan this change implements."
- [x] `openspec/README.md` "Current changes": added this package's entry — mechanically
      required by the OpenSpec change-index guard in `.github/workflows/docs.yml`.

## 4. Proof (dogfood)

- [ ] Dogfood: apply `spec-guardian`'s then `peer-reviewer`'s stated procedure, in character,
      against Phase 1 (`harden-quality-gate-integrity`)'s actual diff, producing
      `openspec/changes/harden-quality-gate-integrity/review.md`.
      **Blocked from this worktree — not fabricated.** Checked, not assumed:
      `git log --all --oneline | grep -i quality-gate` surfaces only pre-existing,
      unrelated `quality-gate` skill history; `git worktree list` shows no
      `harden-quality-gate-integrity` worktree reachable from here. See `design.md`,
      "Dogfood and worktree isolation," for the full account. Left for the orchestrating
      session once this change merges and Phase 1's diff is reachable in the same tree.

## 5. Verification

Run from `claude-foundation/`, per its own `CLAUDE.md`:

- [x] `python -m foundation_tools.validate` — 0 findings.
- [x] `python -m foundation_tools.scan` — 0 findings.
- [x] `python -m foundation_tools.backwards_compat` — 0 findings; `added: {}` post-update.
- [x] `claude plugin validate .` — passed.
- [x] `pytest` — 136 passed. `pytest --cov --cov-report=term-missing` — 96.03% (floor 85%,
      unchanged by this doc-only change; no Python source touched).
- [x] `ruff check .`, `ruff format --check .`, `mypy tools`, `mypy hooks`, `mypy tests` —
      all clean.
- [x] `bash tests/smoke/install_smoke.sh` — OK (plugin validate, hook stdin contracts,
      validator, scanner).
- [x] Manually diffed `name:` frontmatter against each filename stem for both new charters,
      rather than only trusting the validator to catch a typo.
