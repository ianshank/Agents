# Progress Log — langfuse-eval-harness

---
## Session 012 — 2026-07-20

### E2E Windows Cross-Platform Hardening
- Cloned `main` (commit 2537012), provisioned venv + WMI shim, ran full offline
  e2e suite: 18 PASS / 3 FAIL
- Triaged and fixed 3 bugs:
  - `e2e:backend-validation` — `--junitxml` PS 5.1 string concatenation split in
    `@()` context; fixed to string interpolation (SRC-BUG)
  - `e2e:skills+hooks` — WSL bash path mangling (exit 127) + symlink privilege
    denied (WinError 1314); added `_bash_works()` and `_can_symlink()` guards (ENV)
  - `features:validate.py` — F-038 `ModuleNotFoundError` for `braintrust_client`;
    prepended `src/` to `sys.path` in standalone script (ENV)
- Final result: **21 PASS / 0 FAIL / 0 SKIP**

### Changes
- `scripts/run_all_e2e.ps1`: `"--junitxml=$bvXml"` (was `'--junitxml=' + $bvXml`);
  PYTHONPATH save/restore around backend-validation step
- `scripts/validations/F_038.py`: added `src/` to sys.path bootstrap
- `skills/deploy/tests/test_gen_deploy.py`: `_bash_works()` + `BASH_OK` guard
- `skills/quality-gate/tests/test_gen_gate.py`: `_bash_works()` + `BASH_OK` guard
- `skills/project-setup/tests/test_gen_makefile.py`: `_can_symlink()` guard

### Validation evidence
- `run_all_e2e.ps1 -Tiers offline` → 21/0/0 (3 consecutive runs)
- ruff check + format: clean
- All suite coverage floors met

---
## Session 011 — 2026-06-30

### Features
- F-027 (real model-backed target): `ModelTarget` calls a live LLM and returns its
  completion to be scored, unblocking F-024/F-025 against real models; status todo → done
- F-028 (openai-judge skill modernization): brought the last old-convention skill up to
  the v2.0 standard (tests/, ruff.toml, validator_version, CI job); status todo → done
- F-030 (time-windowed judge rate limiting): the throttling deferred from F-022 — a
  sliding-window limiter on BudgetedJudge with an injected clock/sleeper; status todo → done
- F-029 (model-bench marketplace skill): packages F-024/F-025 as a discoverable skill that
  thinly forwards to the harness compare/campaign CLI; status todo → done

### Changes (F-029)
- skills/model-bench: new v2.0 skill — `scripts/run.py` (thin forwarder to
  `eval_harness.cli.main` for compare/campaign, no orchestration re-implemented), vendored
  `validate_skill.py`, `evals/evals.json` + echo-target fixtures (compare + campaign),
  `references/usage.md`, `tests/` (100% on the runner), `ruff.toml`, `.gitignore`
- skills/marketplace.yaml: model-bench entry (v1.0.0); .github/workflows/skills-ci.yml:
  model-bench job (installs the repo packages since it wraps them) + path triggers
- ADR 0015; F_029 validator (offline, drives compare over echo fixtures)

### Validation evidence (F-029)
- `python scripts/validations/F_029.py` exits 0 (offline)
- `validate_skill.py --skill skills/model-bench --tier structural,behavioral` passes;
  `skill_marketplace.py validate` passes; `check_skill_script_drift.py` matches (4 copies)
- runner coverage 100% branch; ruff clean

### Changes (F-030)
- eval_harness config: `JudgeBudgetConfig` gains additive optional `max_per_window` /
  `window_seconds` / `on_rate_limited` (validator requires the two window fields together);
  `SCHEMA_VERSION` unchanged
- eval_harness agent_core_adapter: new `_SlidingWindowLimiter` (deque + injected
  clock/sleeper) consulted in `BudgetedJudge.evaluate` BEFORE the cost reservation
  (block waits, skip returns the sentinel); `build_budgeted_judge` builds it from config
  with stdlib defaults. agent_core.BudgetLedger stays the cap owner; window + cap are
  independent. Absent fields → no limiter (byte-identical)
- ADR 0016; F_030 validator (fake clock, no real sleep); tests in tests/test_budgeted_judge.py

### Validation evidence (F-030)
- `python scripts/validations/F_030.py` exits 0 (offline, fake clock)
- adapter coverage 100% branch (test_budgeted_judge + test_agent_core_adapter);
  ruff + format clean; mypy clean on the adapter

### Changes (F-028)
- skills/openai-judge: added `tests/` (`conftest.py` + `test_run.py`) covering `run.py`
  `--mock`, file-error, and live paths (live path via a fake `eval_harness.judges`
  injected into `sys.modules` — no network); `ruff.toml` (extends repo config, excludes
  the vendored validate_skill.py); `validator_version:'2.0'` frontmatter; version bump
  1.0.0 → 1.1.0 matched in `skills/marketplace.yaml`; `.gitignore`
- .github/workflows/skills-ci.yml: new isolated `openai-judge` job (lint + coverage-gated
  tests + structural/behavioral self-check) and path triggers
- ADR 0014; F_028 validator (reuses validate_skill.py read-only)

### Changes
- eval_harness: new `targets/model.py` — `ModelTarget` registered as `model` (alias
  `llm`), supporting `openai` / `bedrock` / `anthropic` providers selected by a config
  discriminator. Reuses the judges' client-construction + tenacity retry + streamed-delta
  patterns WITHOUT importing the judges component (keeps `targets -> [core, plugins]`,
  leaves the protected judges path untouched). Returns `TargetOutput(output=text,
  latency_ms, metadata={provider,model})`; failures + missing prompt-template keys are
  surfaced as `TargetOutput.error`. `client=` DI seam keeps the whole path offline.
- eval_harness: `targets/__init__.py` imports the new module so the decorator registers.
  No engine or config-schema change — `target.type='model'` wires via the registry,
  `SCHEMA_VERSION` unchanged. No new dependency (reuses the existing
  openai/bedrock/anthropic extras).
- config/model_target.yaml example (env-interpolated, no secrets); ADR 0013;
  F_027 validator (offline, stub client); tests/test_model_target.py

### Validation evidence
- `python scripts/validations/F_027.py` exits 0 (offline, stub client)
- eval_harness: `pytest --cov=eval_harness --cov-fail-under=96` → 96.3% overall;
  `targets/model.py` 100% (branch); ruff + format clean on changed src/tests; mypy clean
  on the new module; `scripts/drift_check.py` still matches the manifest (no new edge)

### Next
- F-028 openai-judge skill modernization; F-030 time-windowed rate limiting;
  F-029 model-bench marketplace skill (wraps F-024/F-025, uses the real target)

## Session 010 — 2026-06-30

### Features
- F-025 (A/B eval campaigns): persistent campaigns with statistical-significance
  testing; status todo → done

### Changes
- eval_harness: new `campaign.py` — `ABCampaignConfig` (two ModelSpec arms, score,
  wilson_z, min_sample), append-only `CampaignStore` (OutcomeStore JSONL pattern),
  `record_run` (runs both arms via EvalEngine, appends per-arm counts), `analyze`
  (accumulates counts, decides via `agent_core.calibration.wilson_interval`:
  cant_tell below power, a/b_better only when powered + disjoint CIs, else
  no_difference), `CampaignResult.to_dict/to_html`
- eval_harness config: additive `ABCampaignConfig` + optional `EvalConfig.ab_campaign`
  (SCHEMA_VERSION unchanged)
- eval_harness CLI: `eval-harness campaign --mode record|analyze`
- ADR 0012; F_025 validator (offline); tests/test_campaign.py

### Validation evidence
- `python scripts/validations/F_025.py` exits 0 (offline)
- eval_harness: `pytest --cov=eval_harness --cov-fail-under=96` → 96.8%
  (campaign.py 99%); ruff + format clean; mypy clean on new module; drift_check
  still matches the manifest (reuses agent_core via the permitted edge, no
  flow_corpus import — airgap preserved)

### Next
- Track 5 step 3 (optional): a marketplace skill wrapping F-024/F-025

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
