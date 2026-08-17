# Tasks: add-openspec-implementation-review

`[P]` = protected path → needs the `eval-change-approved` label + CODEOWNERS review before
merge (`scripts/eval_protected_paths.py`: `.github/**` is protected). No coverage floor
applies to the repo root — this change touches no root/`eval_harness`/`agent-core` source,
only a new, self-contained skill directory plus its registration.

## 1. Skill scaffold

- [x] `skills/openspec-implementation-review/SKILL.md` — 6-section body (Preconditions,
      Procedure, Output contract, Failure handling, Validation gate, Examples), matching
      `docs/SKILL_TEMPLATE.md`'s shape; frontmatter `name`/`version`/`compatibility`/
      `validator_version` in the same field order every other skill uses.
- [x] `references/dispatch-detection.md` — the full plugin-vs-degraded signal explanation,
      moved out of `SKILL.md` to keep exactly 6 numbered sections rather than bolting on a
      7th (`SKILL.md` §2 step 2 links to it).
- [x] `ruff.toml` extending the repo root config, excluding the vendored `validate_skill.py`.
- [x] `.gitignore` (`.skill-validation/`, `__pycache__/`), matching every sibling skill.

## 2. `scripts/implreview/` library

- [x] `locate.py` — `ChangeLocation`/`TaskStatus` dataclasses, `locate_change`,
      `infer_change_id` (branch-name-first, then recent commit subjects, longest-candidate-
      first, alphanumeric-only boundary so `worktree-<id>` and `docs(<id>): ...` both match
      without a hyphen falsely blocking them), `parse_tasks_status` (checkbox tally, immune
      to a same-line `` `[P]` `` protected-path marker), and injectable git helpers
      (`current_branch_name`, `recent_commit_subjects`, `current_tree_sha`) so tests never
      need a real git repository.
- [x] `detect.py` — `detect_dispatch_path`: charter-file presence, plugin-manifest validity,
      and the one real environment signal (`CLAUDE_PLUGIN_ROOT` resolving to this repo's
      `claude-foundation/`), conservative by construction (`plugin` only when the signal is
      actually present).
- [x] `prompts.py` — `build_spec_guardian_prompt`, `build_peer_reviewer_prompt` (plugin path),
      `build_degraded_prompt` (fully self-contained two-pass method for the path this repo's
      sessions actually exercise), `build_dispatch_plan` composing the ordered set for either
      path.
- [x] `compose.py` — `compose_review`: create when absent, append a dated, heading-demoted
      `## Follow-up review` section when a `review.md` already exists, `--overwrite` for the
      rare deliberate exception; re-derives the title from `change_id` rather than trusting a
      dispatched body's own title line.
- [x] `validate.py` — `validate_review_structure`/`validate_review_file`: title, verdict-first
      `## Verdict`/`## Pass 1`/`## Pass 2` ordering, per-pass dates, canonical verdict token
      extraction — calibrated against the two real `review.md` files in this repo (see
      `design.md`), not an invented ideal shape.
- [x] `cli.py` + `scripts/run.py` — `locate`/`detect`/`plan`/`compose`/`validate` subcommands;
      distinct exit codes (`0`/`1`/`2`) so a caller can branch without parsing text.
- [x] `scripts/validate_skill.py` — vendored, confirmed byte-identical (`sha256sum` match) to
      the canonical root `scripts/validate_skill.py`.

## 3. Tests

- [x] `tests/test_locate.py` — checkbox parsing (including the `` `[P]` `` non-collision
      case), branch/commit inference (including the boundary-regex edge cases a first draft
      got wrong — see `design.md`/review notes), `locate_change`'s found/not-found/inferred
      paths, and the git-backed helpers exercised both via an injected fake **and** via the
      real default `_run_git` path (against a genuine non-repo directory, the real repo
      itself, and a monkeypatched `subprocess.run` failure).
- [x] `tests/test_detect.py` — every branch of `detect_dispatch_path` against fixture
      `claude-foundation/` trees, **plus** two tests against the real repository tree with no
      environment override, confirming today's actual, empirically-observed state
      (`degraded`).
- [x] `tests/test_prompts.py` — both prompts' content (target naming, output-shape
      specification) and the degraded prompt's self-containedness (every required method
      element present as a literal string).
- [x] `tests/test_compose.py` — create, append (prior content byte-preserved), overwrite,
      heading demotion, default-date behavior, and that a structurally invalid body is still
      written (never silently dropped) with its errors surfaced.
- [x] `tests/test_validate.py` — every structural error condition, **plus** three tests
      against the real, already-merged `review.md` files in this repo: both genuine
      implementation reviews validate `ok=True` (one of which lacks a final "Overall verdict"
      heading, which is why this validator doesn't require one), and `add-panel-judge/
      review.md` (a different artifact genre — a pre-implementation plan review) correctly
      does not validate, documenting the boundary rather than leaving it assumed.
- [x] `tests/test_cli.py` — every subcommand's success/failure/json branches, in-process via
      `main()`, plus a full locate→plan→compose→validate→compose-again round trip proving the
      append path end-to-end through the CLI alone.
- [x] Coverage: `pytest --cov=implreview --cov-branch --cov-fail-under=95` → **99.83%**
      (verified below, real output).

## 4. Evals (`evals/evals.json`, ≥3 cases required — this ships 7)

- [x] `no-such-change` — a bogus id, real subprocess, non-zero exit + explicit message.
- [x] `locate-happy-path` — a real, fully-checked fixture change locates cleanly.
- [x] `locate-incomplete-tasks-blocks-by-default` / `locate-incomplete-tasks-allow-override` —
      the documented precondition and its override, both exercised for real.
- [x] `detect-degraded-without-foundation` — detection against a fixture repo with no
      `claude-foundation/` at all.
- [x] `validate-hand-written-review-fixture` — a hand-authored `review.md` fixture validates
      structurally.
- [x] `compose-appends-without-clobbering` — two real, chained `python scripts/run.py compose`
      subprocess invocations (a `setup.py` performs the first pass, `run` performs the
      second) against the same scratch repo, asserting both passes' distinguishing content
      survives and the merged document is still structurally valid.

## 5. Registration

- [x] `skills/marketplace.yaml` — new entry, `version: 1.0.0` byte-matching `SKILL.md`
      frontmatter; `python scripts/skill_marketplace.py validate` passes for real.
- [x] `[P]` `.github/workflows/skills-ci.yml` — new dedicated `openspec-implementation-review`
      job (lint + mypy + `pytest --cov-fail-under=95` + `validate_skill.py --tier
      structural,behavioral`), matching the `common`/`repo-invariant-review` job shape.
      Confirmed, by running the `all-skills` job's own reconciliation script locally against
      the landed tree, that **no `EXEMPT` entry is needed** — the job's name matches the
      skill directory exactly.
- [x] `[P]` `scripts/check_skill_script_drift.py` — new entry in `TRACKED_DUPLICATES`
      (`scripts/validate_skill.py` → `.../openspec-implementation-review/scripts/
      validate_skill.py`); `python scripts/check_skill_script_drift.py` passes for real (18
      copies, up from 17).
- [x] `openspec/README.md` "Current changes" — this package's own entry added; the OpenSpec
      change-index guard (`.github/workflows/docs.yml`) logic re-run locally against the
      landed tree, passes.
- [x] `skills/README.md` — added this skill's row to the hand-maintained "Registered skills"
      table and the "Guard/review skills" bullet (not mechanically required by any guard, but
      left stale it would be exactly the "manual list silently drifts from reality" pattern
      ADR 0030 exists to close one layer up).

## 6. Verification

Run for real, output pasted in the implementing session's final report:

- [x] `cd skills/openspec-implementation-review && python -m pytest tests --cov=implreview
      --cov-branch --cov-fail-under=95 -q` → 105 passed, **99.83%** coverage (floor 95%).
- [x] `python -m ruff check . && python -m ruff format --check .` → clean.
- [x] `python -m mypy --config-file ../../pyproject.toml scripts/implreview` → no issues,
      7 source files.
- [x] `python scripts/validate_skill.py --skill . --tier structural,behavioral` → OK; all 7
      evals pass with real, non-`file_exists`-only assertions (`grading.json` inspected).
- [x] `cd ../.. && python scripts/skill_marketplace.py validate` → OK.
- [x] `python scripts/check_skill_script_drift.py` → OK, 18/18 copies match.
- [x] `python scripts/validate.py --tier fast` → OK, 53 validations, unaffected by this
      change (no new/edited F-ID).
- [x] The CLI run for real against a genuine, already-landed change with its own real
      `review.md` (`test-skill-validator-library`): `locate` correctly blocks on its one
      real unchecked "Archive" checkbox (exit 1) and proceeds with `--allow-incomplete`;
      `detect` against the real tree reports `degraded` (charters present, staged, no
      `CLAUDE_PLUGIN_ROOT`); `validate` reads its real `review.md` and extracts `APPROVE WITH
      FOLLOW-UPS` correctly; `compose`'s append path was exercised against a scratch copy of
      that same real file (never the tracked original — confirmed via `git status` showing no
      changes to the tracked file afterward), correctly preserving all 263 original lines and
      appending a demoted, dated follow-up section.

## 7. Explicitly not done here (follow-ons, not gaps)

- [ ] A real `spec-guardian`→`peer-reviewer` plugin-path dispatch, end to end. Not possible
      from any session working this repo directly today (ADR 0028) — see `design.md`, "What
      was actually tested, and what could not be." Revisit once `claude-foundation` is
      extracted (M7) or a session is deliberately started with `--plugin-dir claude-foundation`.
- [ ] Retroactive `review.md` backfill for Phases 1–3 beyond what already exists. `PLAN.md`'s
      own Bootstrapping note calls this a follow-on once this skill exists.
