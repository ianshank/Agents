# Implementation Plan — Orbital-Drift Engineering-Discipline Alignment

**ID:** PLAN-2026-08-17-orbital-drift-alignment
**Date:** 2026-08-17 · **Base commit:** `159460a`
**Motivated by:** a file-by-file comparison of this repo's Claude Code tooling and CI discipline
against a sibling project (Orbital-Drift), independently fact-checked claim-by-claim rather than
trusted. Orbital-Drift has no domain code worth porting (its ML pipeline is still stub
`__init__.py` files) — the transferable value was process, and even that needed correcting: two
of the original comparison's claims about this repo were flatly wrong (it already has a 32-entry
ADR system and already has single-command local/CI parity), and deep verification surfaced six
concrete, independently-confirmed gaps that have nothing to do with Orbital-Drift's own content —
they were found by reading this repo's actual files.
**Scope:** close five verified engineering gaps in this repo's CI/quality-gate discipline and
skill-library test coverage; add two new agent charters (a spec-guardian/peer-reviewer-equivalent
pair) and one new orchestration skill, all authored to this repo's own conventions rather than
copied from the sibling project.
**Non-goals:** porting Orbital-Drift domain code (none exists); adopting Orbital-Drift's per-file
`D-nn` decision-doc format (this repo's global-ID ADR system + `review.md` already cover that
ground, non-interchangeably — see Phase 4 note); a mandatory CI-blocking review gate (shipped
advisory/opt-in this round, Decision Point 2); a scripted eval-suite requirement for new charters
beyond existing precedent (Decision Point 1); retargeting `skills/deploy` for Opik/Langfuse/Phoenix
(grepped, zero connection); backfilling tests/evals onto the three ADR-0030-exempt subjective
skills (`hierarchical-recursive-brainstorm`, `openspec-peer-review`, `openspec-quality-plan` — a
deliberate, documented exemption, not a gap).

---

## Cross-cutting standards

| Standard | Rule | Source of truth |
|---|---|---|
| Backwards compatibility | Skill/agent additions are append-only — never rename/remove `explorer`, `test-runner`, or any existing skill; `GateFacts` field order and the marker-seam contract in the quality-gate generator are preserved | `claude-foundation/CLAUDE.md` compat contract; `skills/quality-gate/scripts/gategen/model.py` |
| No hardcoded values | Every new tunable is a single-sourced constant or config field, never duplicated at call sites; tool-version pins get one source of truth, not seven | `AGENTS.md`; Phase 2 |
| Protected paths | Touching `features.yaml`, `scripts/validations/**`, `.github/**`, or any package's `tests/**` needs the `eval-change-approved` label + CODEOWNERS review | `scripts/eval_protected_paths.py` |
| F-IDs | Claimed at land, not reserved in a proposal | `openspec/project.md` |
| ADR numbering | Global monotonic sequence; next free number taken **at merge time**, not draft time — self-resolving if two branches both want one | `docs/decisions/README.md` |
| Skill registration | `skills/marketplace.yaml` entry version byte-matches `SKILL.md` frontmatter; `python scripts/skill_marketplace.py validate` | `skills/marketplace.schema.json` |
| Agent registration | Drop `<name>.md` in `claude-foundation/agents/`; `python -m foundation_tools.validate`; update `claude-foundation/README.md` Components table + `CHANGELOG.md` + `tests/backwards_compat_baseline.json --update`; `claude plugin validate .` | `claude-foundation/CLAUDE.md` |
| claude-foundation isolation | It is a **staging** directory (ADR 0028), not an installed plugin in this repo's own sessions — nothing outside it imports from it, and dispatching its charters here requires `claude --plugin-dir claude-foundation` | `docs/decisions/0028-claude-foundation-staging.md` |
| Coverage floors | root/`eval_harness` 96, `agent-core`/`behavioral-regression`/`flow-protocol`/`flow-corpus` 95, `claude-foundation` 85, `scripts/` 85, new skills 95 (99 for `dataset-lint`) | per-package `pyproject.toml`; `scripts/.coveragerc` |

## Decision points (defaults applied this round)

1. **Eval rigor for new charters** — PARITY with `explorer`/`test-runner`: no scripted eval suite;
   structural validation + dogfooding on a real change is the proof. A higher bar would be a new
   precedent, not a gap-fill.
2. **Review-loop enforcement** — ADVISORY/opt-in. Not wired into `CONTRIBUTING.md`, `GOVERNANCE.md`,
   protected paths, or CI. This repo has zero precedent for a second-agent-charter blocking gate
   today (existing blocking gates are all CI-mechanical or human/label-based); mandating one is a
   separate, later decision with its own rollout.

---

## Phase 0 — Shared conventions (complete, this document)

Orbital-Drift's own history (`docs/decisions/000-*.md`/`002-*.md` in that repo) records that four
parallel dispatches with no agreed layout produced mutually incompatible artifacts. Pinned before
any worktree fan-out:

1. **File-collision map.** Phases 1-4 are file-disjoint with one soft overlap: Phase 2 and Phase 3
   both concern `.github/workflows/skills-ci.yml`. Resolved by construction — Phase 2 only *reads*
   it (from a new validation script); Phase 3 *edits* it (adds a job, removes an `EXEMPT` entry).
   No merge-order constraint follows from this; either can land first.
2. **ADR numbering.** Next free number at authoring time is **0034**. Not pre-claimed by any
   phase — whichever of Phase 2 or Phase 4 (both may want one) merges first takes it; the next
   claims the following number at *its* merge time.
3. **F-ID claiming.** Same rule against `features.yaml` — claim at land.
4. **Charter template, frozen for Phase 4.** Frontmatter order `name, description, tools, model,
   maxTurns`; body = 1-2 sentence identity + exactly one `## Rules` heading + 5-6 numbered rules;
   ~20-26 lines; zero repo-specific paths (matches `explorer.md`/`test-runner.md`).
5. **Worktree naming.** `worktree-<change-id>`, one per OpenSpec change, all branched from this
   commit. Phase 5 branches from Phase 4's branch (drafted early, rebased before its own merge).

---

## Phase 1 — `harden-quality-gate-integrity`

The coverage gate can currently be made to lie without anyone noticing, two ways: an unguarded
environment variable, and a regex broader than its own governing decision doc claims.

| Area | Files | Protected |
|---|---|---|
| Env-evasion fix | `skills/quality-gate/scripts/gategen/render.py` — extend `_ignored_override_notice` to always cover `COV_FAIL_UNDER`, add a `PYTEST_ADDOPTS` guard (read, warn "this stage is a gate and has no opt-out", unset) in `do_test`/`do_coverage` | no |
| Regeneration | 7 `quality-gate.sh` copies (root, `agent-core/`, `behavioral-regression/`, `claude-foundation/`, `experiments/backend-validation/`, `flow-corpus/`, `flow-protocol/`), regenerated via each file's own `# regenerate:` provenance comment, **not** hand-patched. Root's hand-maintained `do_extra()` (below the marker, generator can't reach it) needs the same guard added by hand. Leave `skills/project-setup/evals/fixtures/with-gate/scripts/quality-gate.sh` (a frozen fixture) untouched | no |
| Coverage-exclude fix | `agent-core/pyproject.toml`, `behavioral-regression/pyproject.toml`, `flow-protocol/pyproject.toml`, `flow-corpus/pyproject.toml` — `exclude_also` `"\\.\\.\\."` → anchored `"^\\s*\\.\\.\\.$"`, matching root/`scripts/.coveragerc`/`claude-foundation`'s already-safe pattern | no |
| Positive controls | `skills/quality-gate/tests/test_gen_gate.py` — new cases: low-coverage fixture fails; high-coverage fixture passes; low-coverage fixture with `COV_FAIL_UNDER=0` injected still fails; same with a coverage-weakening `PYTEST_ADDOPTS` still fails | **yes** |
| Docs | `skills/quality-gate/SKILL.md` §2/§6 (correct the overridability claim); `skills/quality-gate/evals/evals.json` (update `file_contains` assertions, add one for the ignored-override notice text) | no |
| Errata | `docs/decisions/0009-tech-debt-audit-and-compat-surface.md` — `**Errata**` header line restoring its own already-decided intent (its claim that exclude patterns were "aligned" was true in intent, false in the regex text) | no |
| Governance | `features.yaml` row + `scripts/validations/F_0NN.py` (asserts regenerated scripts contain the notices and no longer interpolate raw `COV_FAIL_UNDER`/`COVERAGE_SOURCE`; all 4 `pyproject.toml` carry the anchored regex) | **yes** |

**Declined:** a second env-clearing layer in `.github/actions/run-quality-gate/action.yml`. The
generator is the single source of truth every consumer gets on regeneration; a second place to
keep in sync buys no added safety.

**MCP checkpoint:** before finalizing this phase's `design.md`, verify current coverage.py/pytest-cov
semantics (does `exclude_also` still only *append* to the built-in exclusion set; is exclude-pattern
matching still `re.search`, not full-line) via Context7 rather than trusting training-data memory —
if Context7 is unavailable this session, note the assumption explicitly in `design.md` instead of
asserting it silently.

## Phase 2 — `pin-lockstep-tool-versions`

`ruff==0.15.20`/`mypy==2.1.0` are hand-duplicated across 7 `pyproject.toml` files and 9 `pip
install` lines in `skills-ci.yml`, with a "bump in lockstep" comment but no test enforcing it.

| Area | Files | Protected |
|---|---|---|
| Source of truth | new `scripts/tool_versions.py` (`RUFF_VERSION`, `MYPY_VERSION`) | no |
| Lockstep proof | new `scripts/validations/F_0NN.py` — **read-only** text check of all 7 `pyproject.toml` dev-extras and all 9 `skills-ci.yml` pip-install lines against `tool_versions.py` (deliberately read-only on `skills-ci.yml` — see Phase 0 §1) | **yes** |
| Docs | `AGENTS.md` — point its existing pin bullet at `scripts/tool_versions.py`; new ADR (0034 if it lands first — Phase 0 §2) documenting "drift-tested duplication, not full templating" | no |

**Declined this round:** rewiring the 16 call sites to interpolate from the shared file at install
time — real gain is "drift can't merge silently," which the lockstep proof already delivers;
templating 9 CI job definitions for marginal further benefit is an explicit optional follow-on.

## Phase 3 — `test-skill-validator-library`

`skills/common/skill_validator.py` is the grading engine every other skill's vendored
`validate_skill.py` imports — real, load-bearing code, not a subjective/judgment skill — with zero
measured coverage and no lint/mypy pass today.

| Area | Files | Protected |
|---|---|---|
| Tests | new `skills/common/tests/test_skill_validator.py` — targets confirmed gaps (`grade_file_exists` has no existing test; `_run_eval`'s subprocess mechanics — token rewrite, shell-quoting, timeout — are monkeypatched around, not exercised) without duplicating the 19 existing root-level wrapper-contract tests | no |
| CI wiring | new vendored `skills/common/scripts/validate_skill.py` (registered in `check_skill_script_drift.py`'s `TRACKED_DUPLICATES`); new `common` job in `skills-ci.yml` — ruff + mypy + `pytest --cov=skill_validator --cov-fail-under=95` + `validate_skill.py --skill . --tier structural` (structural only — no `evals/evals.json`, no E2E task; comment notes this is a third case ADR 0030 didn't name: real code, no behavioral surface) | **yes** |
| Cleanup | remove `common`'s `EXEMPT` entry in `skills-ci.yml`'s `all-skills` job | **yes** |
| Addendum (file-disjoint) | `skills/openspec-quality-plan/SKILL.md` §5 — strengthen its self-check list (2 presence-only criteria today vs. 4-5 concrete ones in its two subjective siblings). Prose only, stays structural-tier, no `evals/` added — the ADR 0030 exemption is correct for this skill and is not being revisited | no |

**Declined:** any tests/evals addition to `hierarchical-recursive-brainstorm` or `openspec-peer-review`
— both already have adequately concrete §5 self-check criteria; ADR 0030's exemption stands.

## Phase 4 — `add-foundation-reviewer-charters`

**Decision Point 1 applies.** No spec-guardian/peer-reviewer-equivalent exists; `claude-foundation/agents/`
has only `explorer`/`test-runner`, and no sequential blocking review-loop convention exists to slot
into — this is net-new capability.

| Area | Files | Protected |
|---|---|---|
| Charters | new `claude-foundation/agents/spec-guardian.md`, `claude-foundation/agents/peer-reviewer.md` — Phase 0 §4 template; tools `Read, Grep, Glob` only (no Bash — this repo has no settings.json deny-list backstop, and neither charter needs it); **dynamically discover** a consumer repo's conventions at runtime (try, in order: `CLAUDE.md`, `AGENTS.md`, `openspec/`, `docs/decisions/`, `specs/`, `.specify/`) rather than hardcoding this monorepo's paths, per `claude-foundation`'s own portability law | no |
| Fleet contract | `openspec/AGENTS.md` — add lifecycle rows for both charters; correct "nothing here invents a new agent," which this phase makes literally false | no |
| Registration | `claude-foundation/README.md` Components table (+2 rows), `claude-foundation/CHANGELOG.md` `[Unreleased]`, `claude-foundation/tests/backwards_compat_baseline.json` (regenerated via `--update` — pure addition, append-only-safe, never fails CI, committed anyway per house practice) | no |
| Proof | dogfood: dispatch both charters against Phase 1's merged diff, producing a real `openspec/changes/harden-quality-gate-integrity/review.md` — doubles as that phase's own peer-review artifact and as the charters' functional proof | no |

**Operational precondition, must be stated not assumed:** `claude-foundation/` is staged (ADR 0028),
not an installed plugin in this repo's own sessions. Dispatching `spec-guardian`/`peer-reviewer` here
requires a session started with `claude --plugin-dir claude-foundation`. Phase 5's skill must degrade
gracefully when that precondition isn't met (see below) rather than silently fail to find the agents.

## Phase 5 — `add-openspec-implementation-review` (depends on Phase 4)

**Decision Point 2 applies.** Advisory/opt-in tooling, not a blocking gate.

| Area | Files | Protected |
|---|---|---|
| Skill | new `skills/openspec-implementation-review/` — full artifact-producing shape (`SKILL.md`, `scripts/implreview/`, `scripts/run.py`, vendored `validate_skill.py`, `tests/`, `evals/evals.json` ≥3 cases). Named to *not* collide with `openspec-peer-review` (reviews plan packages; this reviews shipped implementations against their plan — complementary, not duplicate) | no |
| Procedure | locate `openspec/changes/<id>/`, confirm tasks.md checkboxes + CI green, dispatch `spec-guardian` → `peer-reviewer` if `claude-foundation` is plugin-loaded, **else** degrade to a `general-purpose` subagent with the review.md two-pass method inlined so output shape is identical either way; compose `openspec/changes/<id>/review.md` in the `add-panel-judge/review.md` shape (verdict-first, two dated passes, refuted attacks kept) | no |
| Registration | `skills/marketplace.yaml` entry; new dedicated job in `skills-ci.yml` (auto-covered by `all-skills`'s dynamic discovery, no `EXEMPT` needed — confirms correct classification) | **yes** |
| Index | `openspec/README.md` "Current changes" row — mechanically required; `docs.yml`'s OpenSpec-index check fails CI otherwise | no |

**Bootstrapping note:** once this lands, run it retroactively against Phases 1-3's already-merged
implementations for supplementary `review.md` artifacts. A follow-on, not a blocking step here.

---

## Worktree / parallelization strategy

**Wave 1** (parallel, 4 worktrees, all branched from this document's base commit): Phase 1, Phase 2,
Phase 3, Phase 4 — zero interdependency, file-disjoint per Phase 0 §1. Land in any order.

**Wave 2** (sequential, after Phase 4 merges): Phase 5 — may be drafted early against Phase 4's
pre-merge branch to overlap authoring time, rebased onto the integration branch before its own merge.

**Reconvergence:** each phase's branch merges independently into this session's designated working
branch (not 5 separate upstream PRs — this session ships one PR per its own operating constraints);
`CONTRIBUTING.md`'s "one logical change per PR" intent is preserved at the OpenSpec-change level
(one proposal/design/tasks/review package per phase) even though delivery is consolidated.

## MCP usage plan

- **GitHub MCP** — PR creation/monitoring for the consolidated branch, `get_check_run`/`get_job_logs`
  for real CI failure evidence during verification.
- **Context7** — Phase 1 only, at design time, to verify coverage.py/pytest-cov semantics before
  finalizing the env-var hardening design (see Phase 1's MCP checkpoint). Not used elsewhere.
- **Mermaid** — reuse `skills/architecture-drift-guard/scripts/mermaid_gen.py` for any C4 diagram
  need (none of these phases add an import edge, so none should need it). The Mermaid MCP server is
  explicitly declined as a second, redundant, driftable diagram path; a one-off sequence diagram
  (e.g. Phase 5's dispatch flow) is hand-authored inline, matching `add-panel-judge/design.md`'s
  own no-tooling markdown tables.
- No other available MCP server is in scope for this engineering plan.

## Objective peer-review step (after every phase, before "done")

Modeled on `review.md`'s two-pass method: pass 1 pins the tree SHA and re-derives every falsifiable
claim in the phase's `proposal.md`/`design.md`/`tasks.md` against the landed diff (CONFIRMED /
CORRECTED / REFUTED, with evidence); pass 2 (separately dated) attacks the design adversarially,
verifies each attack before keeping it, and keeps refuted attacks rather than deleting them.

- **Phases 1-4:** performed by a `general-purpose` subagent dispatch (the reviewer charters don't
  exist yet, and Phase 4 shouldn't review its own creation with itself).
- **Phase 5 and anything after:** performed by the new `spec-guardian` → `peer-reviewer` charters.
- **Artifact:** `openspec/changes/<id>/review.md`, persisting through `openspec archive` into
  `changes/archive/<id>/review.md`.
- **Enforcement:** a checklist item in each phase's own `tasks.md` "Verification" section, per
  Decision Point 2 — not a CI job, not a protected-path requirement.

## Verification

```bash
# Per-package, every touched package:
./scripts/quality-gate.sh all               # root
make -C agent-core check
make -C behavioral-regression check
make -C claude-foundation check
make -C flow-corpus check
make -C flow-protocol check
make -C experiments/backend-validation check # if backend-validation's own Makefile defines it
make check-all                               # repo-wide fan-out

# Skill-library specific
python scripts/skill_marketplace.py validate
python scripts/check_skill_script_drift.py
python scripts/validate.py --tier fast

# claude-foundation specific (Phase 4)
python -m foundation_tools.validate
python -m foundation_tools.backwards_compat
claude plugin validate .

# Governance
python scripts/validations/F_0NN.py          # one per phase's new F-ID
```

Behavioural acceptance, asserted by tests rather than inspection:

- a deliberately low-coverage fixture fails the regenerated `quality-gate.sh coverage`, with
  coverage.py's own "Required test coverage ... not reached" text;
- the same fixture with `COV_FAIL_UNDER=0` or a coverage-weakening `PYTEST_ADDOPTS` injected into
  the subprocess environment **still fails** (the evasion-closed regression proof);
- a deliberate tool-version mismatch introduced in a scratch check reproduces a lockstep failure;
- `common`'s new CI job is green and `all-skills` no longer lists it in `EXEMPT`;
- both new charters pass `foundation_tools.validate`, and a dogfood run against Phase 1's diff
  produces a non-trivial `review.md` (at least one genuine CONFIRMED/CORRECTED/REFUTED verdict);
- Phase 5's skill produces a structurally valid `review.md` both with and without `claude-foundation`
  plugin-loaded (graceful degradation path exercised, not just the happy path).

## Delivery order

Wave 1 (parallel): Phase 1 → Phase 2 → Phase 3 → Phase 4, any order, each landing independently.
Wave 2 (sequential): Phase 5, after Phase 4. Retroactive `review.md` backfill for Phases 1-3 is a
follow-on once Phase 5 exists.
