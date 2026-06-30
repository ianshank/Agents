# Progress Log — langfuse-eval-harness

---
## Session 009 — 2026-06-30

### Features
- F-024 (multi-model comparison): run one dataset against several targets and
  emit a comparative report; status todo → done

### Changes
- eval_harness: new `comparison.py` — `run_comparison` (reuses `EvalEngine`
  per model, target swapped only), the shared `compare_metric` primitive
  (values + baseline deltas + ranking, None ranked last; reused by F-025), and
  `ComparisonResult.to_dict/to_html` (self-contained deterministic report,
  reusing the F-021 html approach)
- eval_harness config: additive `ModelSpec` + `ComparisonConfig` +
  optional `EvalConfig.comparison` (SCHEMA_VERSION unchanged)
- eval_harness CLI: `eval-harness compare --config … [--offline] [--html] [--json]`
- ADR 0011; F_024 validator (offline, echo targets); tests/test_comparison.py

### Validation evidence
- `python scripts/validations/F_024.py` exits 0 (offline)
- eval_harness: `pytest --cov=eval_harness --cov-fail-under=96` → 97%
  (comparison.py 96%); ruff + format clean on changed src/tests; mypy clean on
  new files; architecture drift_check still matches the manifest (no new edges)

### Next
- Track 3: F-025 A/B campaigns (reuse compare_metric + agent_core wilson_interval)
- Track 5 step 3 (optional): new skill wrapping F-024/F-025

## Session 008 — 2026-06-30

### Features
- F-026 (Langfuse judge-prompt management): pull a judge's system prompt from the
  Langfuse prompt registry instead of inline config YAML; status todo → done

### Changes
- eval_harness: new `prompts.py` (`resolve_prompt`) + `PromptSourceConfig` in
  `config/models.py` + additive optional `EvalConfig.judge_prompt`
  (SCHEMA_VERSION unchanged)
- eval_harness: `LangfuseClient.get_prompt` added as a non-abstract, fail-safe
  method (default None; SDK impl returns None on any SDK/network error) so
  third-party subclasses and the offline path keep working
- eval_harness: `engine.from_config` resolves `judge_prompt` into the judge's
  `system` param before construction; absent judge_prompt → byte-identical
- ADR 0010 (prompt-source seam); F_026 validator; tests/test_langfuse_prompts.py

### Validation evidence
- `python scripts/validations/F_026.py` exits 0 (offline; no Langfuse install)
- eval_harness: `pytest --cov=eval_harness --cov-fail-under=96` → 97% (prompts.py
  100%); ruff + ruff format clean on changed src/tests; mypy clean on changed
  files (pre-existing config/__init__.py yaml-stub note unrelated)

### Next
- Tracks 2/3: F-024 multi-model comparison, F-025 A/B campaigns; Track 5 skills

## Session 007 — 2026-06-30

### Features
- F-010 (calibrated auto-merge gate): closed the last open seam from ADR 0005
  (merge-time `OutcomeRecord` seeding); status `in_progress` → `done`

### Changes
- agent-core: new `agent_core/merge_seed.py` — `seed_pending()` + `already_seeded()`
  + a `python -m agent_core.merge_seed` CLI that writes the initial pending
  `OutcomeRecord` (label=None) at merge time. Reuses `OutcomeStore`/`OutcomeRecord`;
  idempotent (no double-seed); `merged_at` defaults to now-UTC and is injectable
- agent-core: `merge_gate_ci.py` gains default-off `--seed-store`/`--change-id`/
  `--merged-at`/`--agent-version`; seeds only on AUTO_MERGE when the flags are
  present, so absent flags keep behaviour byte-identical
- ADR 0005: marked the seam CLOSED, added the "Audit-label accumulation strategy"
  section (cadence / domain scope / reviewer assignment / exit criterion), checked
  the seeding checklist item
- scripts/validations/F_010.py: added a seam assertion (seed → human-audit resolve)
- features.yaml: F-010 → done with a seam verification clause
- NEXT_STEPS.md: checked the seam + audit-strategy items

### Validation evidence
- `python scripts/validations/F_010.py` exits 0 (all 7 checks incl. the seam)
- agent-core: `pytest --cov=agent_core --cov-fail-under=95` → 98% (merge_seed.py and
  merge_gate_ci.py at 100%); new `tests/test_merge_seed.py` + merge_gate_ci seeding
  tests pass; ruff + ruff format + strict mypy clean on changed files
- Pre-existing, unrelated: `test_detectors.py::test_resolve_repo_from_https_remote`
  fails in this sandbox (git remote resolution); fails on clean HEAD too, not a
  regression from this change

### Next
- Tracks 2–4: F-024 multi-model comparison, F-025 A/B campaigns, F-026 Langfuse
  prompt management

## Session 006 — 2026-06-30

### Features
- Track 0 spec hygiene (no new features): reconciled the registry with NEXT_STEPS.md
- F-009 (architecture drift-guard) status `in_progress` → `done` after green
  validator + drift + freshness checks

### Changes
- features.yaml: F-009 → done; backfilled `implemented_in` provenance SHAs for the
  seven previously-null features (F-017, F-018, F-019, F-020, F-021, F-022, F-023)
  from each feature's landing commit
- NEXT_STEPS.md: checked Dynamic Version (F-017), Parallel Execution (F-018), and
  CSV/Parquet (F-019) under Short Term, with as-built notes replacing the original
  intent text
- progress.md: this entry

### Validation evidence
- `python scripts/validations/F_009.py` exits 0 (skill structural+behavioral,
  drift_check matches manifest, mermaid_gen --check fresh)
- `python scripts/validate.py --tier fast` exits 0 (all fast-tier features pass)
- features.yaml validates against features.schema.json (F-001 green)

### Next
- Track 1: close the F-010 merge-gate seam (merge-time `OutcomeRecord` seeding)
- Tracks 2–4: F-024 multi-model comparison, F-025 A/B campaigns, F-026 Langfuse
  prompt management

## Session 005 — 2026-06-22

### Features
- Phase 0 infrastructure hardening (no new features)
- F-008 formally deferred pending ADR 0004 human checklist

### Changes
- pyproject.toml: coverage gate aligned with CI (85→96), mypy/ruff pinned
- CHANGELOG.md: consolidated unreleased sections into [1.2.0-dev]
- NEXT_STEPS.md: marked completed items, added audit label strategy
- CI workflows: extended path triggers for eval-harness-ci and quality-gates
- .env.example: documented 7 previously undocumented env vars
- .gitignore/.dockerignore: added generated report and merge-gate artifact patterns
- requirements.txt: aligned transitive dependency pins
- features.yaml: F-008 status → deferred

### Metrics
- Tests: 271+ passing
- Coverage: 100% (eval_harness)
- Ruff: clean
- Mypy: clean

## 2026-06-15 — Session 003
**Features worked:** F-003, F-004, F-005
**Status changes:** F-003 todo -> done, F-004 todo -> done, F-005 todo -> done
**Structural changes:**
- Added central `scripts/validate_skill.py` for tiered structural & behavioral validation.
- Implemented first self-validating skill `skills/openai-judge/` conforming to structural rules and behavioral evals.
- Integrated Langfuse tracing into CLI/engine with fallback default credentials (`LANGFUSE_SECRET_KEY="sk-lf-e220d788-d2e0-4e82-bbde-6d1a57ba149f"`, `LANGFUSE_PUBLIC_KEY="pk-lf-ad617cfc-ce1b-4c23-8c76-7868605ee6f1"`, `LANGFUSE_BASE_URL="https://us.cloud.langfuse.com"`).
- Added automatic trace linking to dataset run items and fallback no-op decorators.
- Added comprehensive unit tests for `validate_skill.py` and Langfuse client fallback logic.
**ADRs:** Added ADR-0002 (Skill Framework) and ADR-0003 (Langfuse Integration).
**Validation evidence:** `python scripts/validate.py --tier fast` exits 0 with 5 done. `pytest --cov=eval_harness tests/` passes 86 tests with 93% coverage.
**Next:** Seed additional pipeline and judge features.

## 2025-06-15 — Session 002
**Features worked:** F-001, F-002
**Status changes:** F-001 todo -> done, F-002 todo -> done
**Structural changes:** Initialized harness framework (HARNESS_SPEC.md, features.yaml, schema, scripts).
**ADRs:** Added ADR-0001 (OpenAI-compatible judge design).
**Validation evidence:** `python scripts/validate.py --tier fast` exits 0.
**Next:** Seed additional features for the eval harness roadmap.

## 2025-06-15 — Session 001
**Features worked:** F-002 (OpenAI/Nemotron Integration)
**Status changes:** F-002 todo -> done
**Structural changes:** Added openai, tenacity deps. Created OpenAIJudge, config files, tests.
**ADRs:** None (pre-harness session).
**Validation evidence:** pytest --cov: 50 passed, 94% coverage.
**Next:** Integrate spec-driven harness framework.
