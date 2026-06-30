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
- [ ] **Seed merge-gate records (F-010 seam)** — write the initial pending `OutcomeRecord`
  (`change_id` / `domain` / `raw_confidence` / `merged_at`) at merge time so the labeller and
  audit sampler have data to resolve (the only seam left open by ADR 0005; detection is wired).
- [ ] **Accumulate audit labels** — run `audit_sampler` to build per-domain HUMAN_AUDIT
  history before any domain can leave cold-start ESCALATE, then enable per the ADR 0005 checklist.
- [ ] **Audit label accumulation strategy** — define cadence, domain scope, and reviewer assignment for building HUMAN_AUDIT history (prerequisite for F-010 activation per ADR 0005).

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
- [ ] **Dynamic Version** — Use `setuptools.dynamic.version` to derive version
  from `version.py` and eliminate duplication in `pyproject.toml`.
- [ ] **Parallel Execution** — Add `asyncio`/`concurrent.futures` option to
  `EvalEngine` for large datasets.
- [ ] **CSV/Parquet Dataset Source** — Extend dataset support beyond JSONL/inline.
- [x] **`py.typed` Marker** — Ship PEP 561 marker for downstream type checkers.

## Medium Term (v1.3.0)

- [ ] **Skill Marketplace** — Centralized registry for community-contributed
  skills with versioned SKILL.md validation.
- [x] **Weighted/Ensemble Scoring** — Support composite scores from multiple
  scorers with configurable weights (F-020: `weighted` CompositeScorer).
- [x] **Dashboard Export** — Rich HTML report generation from `RunResult`
  (F-021: self-contained `html_file` sink, inline SVG, deterministic).
- [x] **Rate Limit Budget** — Configurable token/request budgets for judge calls
  (F-022: `JudgeBudgetConfig` + `BudgetedJudge`, cumulative cap via agent_core
  `BudgetLedger`; time-windowed throttling deferred).

## Long Term

- [ ] **Multi-model Comparison** — Run the same dataset against multiple models
  and produce comparative reports.
- [ ] **A/B Eval Campaigns** — Persistent eval campaigns with statistical
  significance testing.
- [ ] **Langfuse Prompt Management** — Pull judge prompts from Langfuse prompt
  registry instead of config YAML.
