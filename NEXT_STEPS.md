# Next Steps

## Recently Landed — Quality & Eval-Integrity Gates

- [x] **Skill-script drift guard** — CI guard that pins vendored skill copies of
  `validate_skill.py` to the canonical repo-root copy (`scripts/check_skill_script_drift.py`);
  uniform 95% coverage floor across all packages and skills; shared `scripts/_cli.py` logging
  helper. Rationale + kept compatibility surface recorded in ADR 0009.
- [x] **Regression Gate (F-006)** — net-new ruff/offline-test diff vs an isolated HEAD
  worktree baseline (`scripts/regression_gate.py`).
- [x] **Protected-Path Guard (F-007)** — CODEOWNERS + label-checked CI guard over the
  evaluation-defining surface (`scripts/check_protected_changes.py`).
- [x] **Auto-Fix Loop design (F-008)** — inert, disabled scaffolding + ADR 0004.
- [x] **Architecture Drift-Guard (F-009)** — import-graph → C4-component drift + freshness
  gate over `eval_harness` and `agent_core` (`skills/architecture-drift-guard/`).
- [x] **Calibrated auto-merge gate (F-010, default-off)** — pure `agent_core` decision
  subsystem (`merge_gate`, `outcome_store`, `outcome_labeller`, `audit_sampler`,
  `merge_gate_ci`) with real git/GitHub outcome detectors (`detectors.py`); ADR 0005.
  Auto-merges nothing unless `ENABLE_CALIBRATED_AUTOMERGE` is set.
- [ ] **Make gates required** — add `quality-gates` jobs to branch-protection required
  checks once they have soaked.
- [ ] **Enable auto-fix loop** — only after the ADR 0004 human checklist is complete.
- [x] **Seed merge-gate records (F-010 seam)** — `agent_core/merge_seed.py` writes the initial
  pending `OutcomeRecord` (`change_id` / `domain` / `raw_confidence` / `merged_at`) at merge
  time (idempotent, default-off integration in `merge_gate_ci`); closes the only seam ADR 0005
  left open. Detection was already wired.
- [ ] **Accumulate audit labels** — run `audit_sampler` to build per-domain HUMAN_AUDIT
  history before any domain can leave cold-start ESCALATE, then enable per the ADR 0005 checklist.
- [x] **Audit label accumulation strategy** — cadence, domain scope, and reviewer assignment
  defined in ADR 0005 ("Audit-label accumulation strategy" section).

## Immediate (Pre-v1.2.0)

- [x] **Rotate Leaked Credentials** — A Langfuse secret/public key pair was committed
  in git history. Rotate the affected keys in the Langfuse dashboard and update `.env`
  files. (Key material intentionally omitted here; see the original incident record.)
- [x] **Pin Vulnerable Dependencies** — Upgrade `urllib3>=2.7.0`, `idna>=3.15`,
  `pygments>=2.20.0`, `requests>=2.33.0` per Snyk scan results.
- [ ] **Enable Snyk Code (SAST)** — Upgrade the Snyk org plan to enable static
  analysis of Python source code.
- [x] **BedrockJudge Tests** — Add mocked boto3 tests (similar to OpenAIJudge
  pattern) to close the last coverage gap.

## Short Term (v1.2.0)

- [x] **CI/CD Pipeline** — GitHub Actions workflows for test, lint, type-check,
  feature validation, regression + eval-integrity gates, and Snyk scan on every PR.
- [x] **Dynamic Version** — Derive `__version__` dynamically via
  `importlib.metadata`, with a `0.0.0-dev` fallback for editable/source installs;
  `SCHEMA_VERSION` decoupled from the package version (F-017).
- [x] **Parallel Execution** — `ThreadPoolExecutor`-based parallel item execution
  with configurable `max_workers`; `max_workers=1` preserves byte-identical
  sequential behaviour (F-018, ADR 0008).
- [x] **CSV/Parquet Dataset Source** — `CsvDataset` (`csv`/`csv_file`) and
  `ParquetDataset` (`parquet`/`parquet_file`) with column mappings and `DATA_ROOT`
  path confinement (F-019).
- [x] **`py.typed` Marker** — Ship PEP 561 marker for downstream type checkers.

## Medium Term (v1.3.0)

- [x] **Skill Marketplace** — Centralized registry for community-contributed
  skills with versioned SKILL.md validation (F-023: `skills/marketplace.yaml` +
  schema + `scripts/skill_marketplace.py`, reusing `validate_skill.py` read-only).
- [x] **Skills brought up to date** — `openai-judge` (the last old-convention
  skill) modernized to the v2.0 standard: `tests/` with a ≥95% coverage gate,
  `ruff.toml`, `validator_version: '2.0'` frontmatter, and a dedicated
  `skills-ci.yml` job (F-028, ADR 0014). All three skills now share one bar.
- [x] **Weighted/Ensemble Scoring** — Support composite scores from multiple
  scorers with configurable weights (F-020: `weighted` CompositeScorer).
- [x] **Dashboard Export** — Rich HTML report generation from `RunResult`
  (F-021: self-contained `html_file` sink, inline SVG, deterministic).
- [x] **Rate Limit Budget** — Configurable token/request budgets for judge calls
  (F-022: `JudgeBudgetConfig` + `BudgetedJudge`, cumulative cap via agent_core
  `BudgetLedger`; time-windowed throttling deferred).
- [x] **Time-windowed Rate Limiting** — The throttling deferred from F-022:
  optional `max_per_window`/`window_seconds`/`on_rate_limited` on
  `JudgeBudgetConfig` drive a sliding-window limiter in `BudgetedJudge` with an
  injected clock/sleeper (block-or-skip), independent of the cumulative cap
  (F-030, ADR 0016). Additive, off by default, `SCHEMA_VERSION` unchanged.

## Long Term

- [x] **Multi-model Comparison** — Run the same dataset against multiple targets
  and produce a comparative report (F-024: `ComparisonConfig` + `run_comparison`
  reusing `EvalEngine` per model, the shared `compare_metric` primitive, a
  self-contained HTML/JSON report, and an `eval-harness compare` CLI; ADR 0011).
- [x] **Real Model-backed Target** — `ModelTarget` (`type: model`, alias `llm`)
  calls a live OpenAI-compatible / Bedrock / Anthropic endpoint and returns the
  completion to be scored, so F-024/F-025 run against real models (F-027,
  `src/eval_harness/targets/model.py`, ADR 0013). Reuses the judges' client +
  retry patterns without importing the judges component (airgap preserved); no
  schema bump, no new dependency, credentials env-only, `client=` DI seam keeps
  it offline-testable.
- [x] **A/B Eval Campaigns** — Persistent eval campaigns with statistical
  significance testing (F-025: `ABCampaignConfig` + `CampaignStore` accumulating
  per-arm counts across runs, `analyze` deciding via `agent_core.wilson_interval`
  with an explicit can't-tell-below-power bucket, and an `eval-harness campaign`
  CLI; ADR 0012).
- [x] **Langfuse Prompt Management** — Pull judge prompts from the Langfuse prompt
  registry instead of config YAML (F-026: `PromptSourceConfig` + `resolve_prompt`
  + `LangfuseClient.get_prompt`, additive `EvalConfig.judge_prompt`, YAML fallback;
  ADR 0010).
