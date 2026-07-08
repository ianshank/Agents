# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.3.0-dev] — Unreleased

### Fixed
- **`py.typed` now ships in the root wheel (PEP 561)**: `src/eval_harness/py.typed` was
  missing and there was no `[tool.setuptools.package-data]` stanza, so the root `eval_harness`
  package was not advertised as typed to downstream consumers (the sub-packages already shipped
  theirs). Added both; verified the built wheel contains `eval_harness/py.typed`.
  Making the package typed also made the repo's own `mypy` resolve `eval_harness` against its
  real types, which (a) required adding `src` to `[tool.mypy] mypy_path` so the path-based
  `mypy src/eval_harness` names files by the package (not `src.eval_harness.*`) and stops
  resolving each file twice, and (b) surfaced 32 latent type mismatches in validation scripts
  and Phoenix tests. All fixed with no field-type loosening: config gates now build via
  `EvalConfig.model_validate({...})` (Pydantic coerces the raw mapping, mirroring YAML loading),
  the two Phoenix tests use a real `RunResult` and proper None-narrowing, and a few
  implementation-detail reaches use `cast(...)` with comments.

### Changed
- **Gap-analysis remediation round** (`docs/gap-analysis-2026-07-remediation.md`): a targeted
  tech-debt pass on top of the size-budget work. Config-drove the one remaining hard-coded
  threshold (`BRConfig.sycophancy_label_threshold`, additive/backwards-compatible); extracted
  two duplicated, drifted `agent_core` idioms into reusable stdlib utilities
  (`subprocess_util.run_failsafe`, `atomic_io.atomic_write_text`) — recovering the logging the
  drifted copies had lost; added structured logging to the `behavioral_regression` CLI's report
  writes and decision; and decomposed `validate_skill.check_behavioral` below the function-length
  budget (5 vendored copies synced). Hardened the new `check_size_budget` gate and `F_032` against
  crashes on bad input, and typed the `package_validate` error sink. All coverage floors,
  `ruff`/`mypy --strict`, and the eval-integrity/drift guards stay green; no schema bump, no new
  dependency. The gap-analysis doc records what was intentionally left (cohesive long functions,
  pure-core logging) and why.
- **Merged latest `main`** (E2E harness + Windows/cross-platform fixes, below) into this branch.
  Two areas that `main` independently fixed had been refactored here, so the fixes were ported
  forward rather than lost: `main`'s byte-oriented git-plumbing runner (the Windows CRLF-in-stdin
  fix for `store_sync`) now lives in the shared `subprocess_util.run_failsafe` — so `detectors`
  and `store_sync` both get it — and `main`'s portable `_run_eval` (`sys.executable` rewrite,
  `stdin=DEVNULL`) is now the single execution helper behind `validate_skill.check_behavioral`'s
  decomposed `_run_one_eval`. `_commit_store` is re-exported from the `store_sync` package for
  `main`'s round-trip tests. No behaviour lost from either side; all suites/gates green.

### Tooling — one-command E2E / user-journey harness
- **`scripts/run_all_e2e.ps1` + `docs/e2e-runbook.md`:** a single orchestrator that runs
  every test across the monorepo and writes an aggregated report to `artifacts/e2e-report/`
  (per-suite JUnit XML + `summary.json`/`summary.md`). Tiers: (A) all package pytest suites
  with their coverage floors; (B) every `features.yaml` functionality gate via
  `scripts/validate.py`; (C) user-journey CLIs (`eval-harness run/compare/campaign/list-plugins`,
  `bregress`, `agent_core.merge_gate_ci`, `skill_marketplace.py`) plus the skill/hook
  `*_e2e`/`test_end_to_end` tests; (D) credential-gated live integrations (Langfuse/Phoenix
  smokes + live judge/sink journeys, skipped cleanly when creds are absent). A pre-flight import
  guard and a per-suite "> 0 tests collected" assertion prevent a mis-set `PYTHONPATH` from
  reporting a vacuous green run.

### Fixed — Windows / cross-platform portability
- **`agent_core.store_sync`:** the git-plumbing runner used `text=True`, so on Windows
  stdin `\n` was CRLF-translated — a `git mktree` line's trailing `\n` became `\r\n` and the
  tree entry name became `<file>\r`, breaking every push/pull round-trip. The runner is now
  byte-oriented (UTF-8 encode/decode), so `\n` stays `\n` on all platforms.
- **`foundation_tools.validate`:** findings emitted OS-native `\` path separators; now
  `.as_posix()` so findings are deterministic (forward slashes) across platforms.
- **`skills/architecture-drift-guard` e2e test:** the generated manifest embedded a Windows
  `\` path inside a YAML double-quoted scalar (invalid escape sequences); it now uses forward
  slashes.
- **Phoenix optional-dependency tests** (`tests/test_phoenix_{tracing,sink,eval_judge}.py`):
  the "SDK-absent failsafe" tests assumed the extra was uninstalled and failed in an
  all-extras environment; they are now hermetic via `sys.modules[...] = None` injection (the
  repo's established idiom), so they exercise the failsafe path in any environment.
- **`claude-foundation` symlink test:** skips cleanly when the host lacks the symlink privilege
  (Windows without Developer Mode, `WinError 1314`) instead of erroring.
- **`scripts/validate_skill.py`** (canonical + all 4 drift-guarded skill copies): eval commands
  ran bare `python`, which on Windows resolved to a non-venv interpreter without the skill's
  dependencies. The runner now rewrites a standalone `python` token to `sys.executable`; the
  three POSIX-only `command_exit_zero` evals in `architecture-drift-guard/evals/evals.json`
  were rewritten as cross-platform python one-liners (no `/dev/null`, `test $? -eq 1`, or pipes).

### Added
- **Structural size-budget enforcement (ADR 0019):** two of the project's four documented
  structural limits are now enforced gates instead of prose. Cyclomatic complexity `< 15`
  is enforced repo-wide via ruff `C901` + `[tool.ruff.lint.mccabe] max-complexity = 14`
  (added to the root and every sub-package config; skills inherit it). File length `≤ 500`
  is enforced by a new stdlib gate `scripts/check_size_budget.py`, wired into
  `quality-gates.yml` with its own unit tests under the `scripts/` ≥85% floor. Function
  length (`≤ 50`) and public-method count (`≤ 15`) are reported as **non-blocking warnings**
  (41 functions exceed the line budget — argparse `main()`s and validation gates — so
  hard-gating them would churn protected paths; the backlog is surfaced, not hidden).
  Pre-existing complexity violations in `behavioral_regression.config`, `validate_skill`,
  and `eval-corpus-forge` were refactored by extracting single-responsibility helpers;
  behaviour and error messages are unchanged.
- **Browsable HTML coverage artifact:** `eval-harness-ci.yml` now emits `--cov-report=html`
  and uploads `htmlcov/` as the `coverage-html` artifact (one matrix leg).
- **Per-package gap-analysis docs:** `flow-corpus/GAP_ANALYSIS.md` and
  `behavioral-regression/GAP_ANALYSIS.md` mirror `agent-core/GAP_ANALYSIS.md`, so every
  package now carries the same candour surface (design choices, known limitations, coverage
  residual).
- **Live Phoenix validation (opt-in workflow_dispatch):** `.github/workflows/phoenix-live.yml`
  runs a two-job matrix — `dep-resolve` performs a `pip install '.[phoenix,phoenix-evals,parquet]'
  --dry-run` to surface the pandas/numpy vs `pyarrow>=14,<20` interaction without installing,
  and `live` boots a self-hosted `arize-phoenix==17.18.0` via `phoenix serve` and exercises
  the real OTLP tracing surface plus the Phoenix evals judge. Companion tests live in
  `tests/test_phoenix_live.py` (marker `@pytest.mark.integration`), which skip cleanly when
  the extras aren't installed or the endpoint/secret env vars aren't set. Project name, span
  name, judge name, and eval model are all env-driven (`PHOENIX_LIVE_PROJECT`,
  `PHOENIX_LIVE_SPAN_NAME`, `PHOENIX_LIVE_JUDGE_NAME`, `PHOENIX_EVAL_MODEL`) with defaults, so
  reruns on the same collector namespace cleanly. Both jobs carry `timeout-minutes: 20` and
  the OTLP endpoint uses the explicit `/v1/traces` path. Rollback is fully reversible — see
  `docs/phoenix-spike.md`.
- **`AGENTS.md`** at the repo root — orientation for coding agents (Claude Code, Codex,
  Copilot, Gemini). Codifies the non-hardcoded-values constraint, protected-paths guard,
  seam pattern for SDK-optional integrations, testing conventions, and the pre-PR checklist.
  Complements `README.md` without duplicating it.

### Hardening
- **Real-data activation gap-analysis round (F-032…F-035):** post-implementation
  adversarial review + CI-parity battery fixed three defects before merge: reader
  jobs (shadow, audit-select) no longer strip checkout credentials (on a private
  repo an unauthenticated data-branch fetch reads as failure — the weekly audit
  would hard-fail forever and the shadow would always cold-start empty);
  `store_sync` preserves malformed/forward-incompatible store lines verbatim
  through merges instead of crashing every sync — or worse, deleting them on the
  next push (`_unparsed` stats key, round-trip tested); the `MERGE_GATE_STORE`
  repo variable is honored by every store-touching job, not just the acting gate
  (a set variable would have silently split readers from writers). Plus: shared
  real-git test helpers (`agent-core/tests/gitrepo.py`), semver-major-compatible
  domain-mapping schema, empty-tree diff fallback for a parentless first push,
  named exit-code constants, richer sync failure logs; `store_sync` at 100%
  branch coverage.
- **Operational-scripts quality gates (F-031):** `scripts/` (44 files) was un-linted,
  un-typed, and coverage-unmeasured by CI (see `docs/gap-analysis-2026-07.md` for the measured
  baseline). Fixed all 169 ruff findings and 19 mypy errors; per-file-ignores scoped only to
  the deliberate patterns (sys.path bootstrap E402, feature-ID module names N999, docstring
  typography RUF00x); vendored `validate_skill.py` copies resynced (drift guard green). Added
  46 unit tests for the previously-untested operational scripts (`validate.py` 16%→97%,
  `select_next.py` 0%→100%, `init.py` 0%→100%) and a dedicated coverage gate
  (`scripts/.coveragerc`, `fail_under = 85`, branch measurement, 93.21% at introduction) that
  excludes `validations/F_*` — those are themselves one-shot CI gates. `eval-harness-ci` now
  runs `ruff check`/`ruff format --check`/`mypy` over `scripts/` plus the new coverage gate,
  enforced by `scripts/validations/F_031.py`.
- **Enforced ≥85% coverage on all new tooling:** `scripts/skill_marketplace.py` and the
  `scripts/validations/F_020..F_023.py` validators are now coverage-gated in the quality-gates
  tooling step (previously run but unmeasured, since the library coverage omits `scripts/`). Added
  `tests/test_validation_scripts.py` to exercise each validator's `main()` and the shared helper.
- **De-duplicated `_as_text`** into `eval_harness.core._serialize.as_text`, reused by both the
  scorers and the HTML sink instead of two copies.
- **Single-sourced validator boilerplate** into `scripts/validations/_common.py`
  (`configure_logging` reuse, `check`, `report`), removing the per-script `logging.basicConfig`
  and `_check`/summary duplication.
- **Configurable budget sentinel:** `BudgetedJudge`'s budget-exhausted score is now
  `JudgeBudgetConfig.skip_score` (default 0.0, backwards-compatible) instead of a hardcoded
  literal; the HTML sink palette is hoisted to named class constants.

### Added
- **Real-data activation (F-032…F-035, ADR 0018):** the calibrated merge gate's
  first real data path. `agent_core.store_sync` persists the outcome store on the
  `merge-gate-data` branch (canonical deterministic merge because
  `OutcomeStore.resolved()` is file-order dependent; plumbing commits; bounded
  retry-with-backoff for concurrent writers; CLI `pull/push/stats`, exit codes
  0/4/5). New workflows: `outcome-labeller.yml` (daily passive labels behind a
  `checks: read` + full-history precondition guard, so detector fallback cannot
  mint optimistic `timeout_clean` labels), a `shadow` job in
  `calibrated-merge-gate.yml` (log-only decision on every PR — decisions never
  fail the job — plus a `human/<domain>` observability decision and per-domain
  store stats in the step summary), `merge-gate-seed.yml` (one pending record per
  push to main, seeded under the reserved `human/<domain>` namespace at
  confidence 0.0 per ADR 0018 §5), `merge-gate-audit.yml` (weekly unbiased
  selection surfaced as deduped GitHub issues; sampling knobs via repo
  variables), and `merge-gate-verdict.yml` (dispatch-only writer of HUMAN_AUDIT
  with environment + allowlist authorization and env-indirected inputs). New
  operational scripts `merge_gate_context.py` (strict path→domain mapping from
  `config/merge-gate-domains.yaml`, protected-path detection, ChangeContext
  JSON), `record_audit_verdict.py` (idempotent, SHA-validated verdict wrapper),
  `audit_issue_sync.py` (pure issue dedupe/render); validations
  `F_032`–`F_035`; F-036 recorded as deferred.

### Added
- **Skill marketplace (F-023):** new centralized, schema-validated skill registry
  (`skills/marketplace.yaml` + `skills/marketplace.schema.json`) and a
  `scripts/skill_marketplace.py` CLI (`validate`/`verify`/`list`). The CLI reuses
  `scripts/validate_skill.py` **read-only** (`parse_frontmatter`, `check_structural`) and adds
  marketplace rules on top: a semver `version` in each `SKILL.md` frontmatter that matches the
  registry entry, matching and unique names, and a real skill directory. Existing skills gain an
  additive `version:` frontmatter key. `validate_skill.py` is not modified, so the skill-script
  drift guard is unaffected.
- **Judge budget cap (F-022):** new `BudgetedJudge` + `build_budgeted_judge` in
  `agent_core_adapter` wrap a `Judge` with a cumulative per-run cost cap enforced via the
  existing `agent_core.BudgetLedger` (no reimplementation). Each `evaluate` **reserves**
  `cost_per_call` before delegating, under a lock, so the cap holds under parallel execution and
  no admitted call is retroactively rejected. On exhaustion it raises `BudgetExceededError` or
  returns a sentinel verdict, per `on_exceeded`. Configured via the optional, default-off
  `JudgeBudgetConfig` and wired in `EvalEngine.from_config`; agent_core is imported lazily so the
  offline path stays dependency-free. This is a cumulative budget cap, not time-windowed rate
  limiting (deferred); since no live token signal exists at the judge call site, `cost_per_call`
  is a configured per-call estimate. `SCHEMA_VERSION` unchanged.
- **Weighted / ensemble scoring (F-020):** new `CompositeScorer` (registered as `weighted`,
  aliases `composite`/`ensemble`) owns child scorers built once from the registry and combines
  their values as a weight-normalised mean (`Σ wᵢ·vᵢ / Σ wᵢ`) into one `ScoreResult`, recording
  the per-child breakdown in `ScoreResult.metadata['components']`. An `llm_judge` child still
  receives `ctx.judge`. `pass_threshold` drives the composite pass flag; without it the composite
  aggregates child verdicts. Configured via `ComponentSpec` params — no config-schema change,
  `SCHEMA_VERSION` unchanged.
- **Score metadata now serialised:** `RunResult.to_dict()` gains an additive per-score
  `metadata` key so the composite breakdown (and any scorer metadata) reaches the JSON/HTML
  sinks. Backwards-compatible — existing keys are unchanged.
- **HTML dashboard export sink (F-021):** new `HtmlFileSink` (registered as `html_file`,
  alias `html`) renders a `RunResult` into a single self-contained HTML report — inline CSS
  and inline-SVG metric bars, no external assets or CDN links. Output is a pure function of the
  `RunResult` (byte-identical for a fixed run); user output is HTML-escaped; `pass_rate=None`
  renders `n/a`. Configured via existing `ComponentSpec` params (`path`/`title`/`embed_items`/
  `bar_width_px`) — no config-schema change, `SCHEMA_VERSION` unchanged. Reuses the
  dependency-free string-built rendering approach from `behavioral_regression.report.to_html`.

### Fixed
- **`agent_core.detectors.resolve_repo` under git URL rewrites:** now reads the declared
  remote via `git config --get remote.origin.url` instead of `git remote get-url origin`,
  which applies `url.<base>.insteadOf` rewrites and silently broke `owner/repo` detection
  (returned `None`) on machines with SSH/proxy rewrite rules. Same signature and contract.

### Docs
- **Gap analysis 2026-07** (`docs/gap-analysis-2026-07.md`): measured lint/type/coverage
  baseline across all packages, skills, and scripts; findings and remediation checklist.
- **`claude-foundation` plugin plan** (`docs/plans/claude-foundation/`): peer review
  (REVIEW.md), corrected execution-ready plan (PLAN.md), and pinned doc sources for the
  planned reusable Claude Code plugin repository. Planning artifacts only — nothing in this
  repo depends on them yet.
- **ADR 0017 — claude-foundation reconciliation** (PLAN.md M7 prerequisite): this repo keeps
  its four domain skills and custom marketplace unchanged; the plugin supplies only the
  generic `foundation:*` layer and is consumed by installing a pinned tag, never by vendoring.
  Records the routing rule (generic → foundation, domain → here) and the rejected
  alternatives (migrate, dual-publish, in-repo subdirectory plugin).

### Added
- **`claude-foundation/` staging directory** — the full foundation plugin (PLAN.md M0–M6)
  implemented and staged for extraction to its own repository: `.claude-plugin` manifests
  (plugin name `foundation`, official validator green), skills `plan` / `code-review` /
  `test-first` / `c4-docs` each with ≥3 eval cases, subagents `explorer` / `test-runner`
  (least-privilege tools, alias-only models), hooks `pre-tool-guard` (fail-closed) /
  `post-edit-verify` / `session-logger` (fail-open, JSONL via `CLAUDE_FOUNDATION_LOG_DIR`),
  and the `foundation_tools` package (doc-derived schema validator, no-hardcode scanner,
  skill-creator eval gate) at 94% branch coverage with mypy strict. CI workflow ships inert
  (activates on extraction); staging adds no jobs to this repo's CI. See ADR 0017 for why
  the final home is a separate repository.

## [1.2.0-dev] — Unreleased

### Tech-debt cleanup
- **Skill-script drift guard:** new `scripts/check_skill_script_drift.py` pins the canonical
  `scripts/validate_skill.py` and fails CI if any vendored skill copy diverges (SHA-256
  compare; declarative `TRACKED_DUPLICATES`). Wired into `quality-gates.yml`. The skill copies
  remain duplicated **by design** for portability — see
  [ADR 0009](docs/decisions/0009-tech-debt-audit-and-compat-surface.md).
- **Uniform 95% branch-coverage floor:** raised both skills' gates 90 → 95 in `skills-ci.yml`
  with margin tests (eval-corpus-forge 98%, architecture-drift-guard 100%). Enabled
  `branch = true` on the root harness, skills, and tooling job (sub-packages already had it);
  closed the partial branches it surfaced via `tests/test_branch_coverage.py` and aligned the
  root `exclude_lines` with the sub-packages'. The quality-gate tooling stays at 85% by design
  (ADR 0009).
- **Reusable CLI logging:** extracted the duplicated `logging.basicConfig` block into
  `scripts/_cli.py` (`configure_logging`), reused across `validate.py`, `regression_gate.py`,
  `select_next.py`, `init.py`, and `check_protected_changes.py`. Removed the dead `_venv_pip`
  helper in `init.py`.
- **Robustness:** `validate.py` now routes both `python ` and `python3 ` validation commands
  through the active interpreter (`_route_to_active_python`); `check_skill_script_drift.py`
  serializes via `dataclasses.asdict`. Modernised typing in the touched scripts (ruff `UP`).

### Fixed
- Aligned `pyproject.toml` coverage gate (`fail_under`) with CI enforcement (85→96).
- Closed test coverage gaps: 93.8% → 100% (merged `feat/coverage-gaps`).

### Flow Calibration Corpus

A calibration corpus of agentic flow variants that gives the validation harness a diverse,
oracle-backed, *populated* sample to calibrate against and to prove it generalizes beyond a
single flow shape. Built as two new packages whose isolation from the harness is enforced
**structurally** by the existing grimp drift gate.

### Added
- **Contract + structural airgap (F-011):** new `flow-protocol/` package — the *only* shared
  surface between corpus and harness: frozen Pydantic v2 `FlowResult` / `OracleResult` /
  `ConfidenceChannel` with a `PROTOCOL_VERSION` semver + migration chain. `architecture.yaml`
  declares `flow_protocol`/`flow_corpus` components with the only edges being
  `flow_corpus → {flow_protocol, agent_core}`; a negative test proves a forbidden
  `flow_corpus → eval_harness` import trips `drift_check.py`. `architecture.yaml` added to the
  eval-integrity protected paths.
- **Two-way version pin (F-012):** `flow_corpus.pinning.verify_pins()` pins the `flow_protocol`
  and `agent_core` versions it was built against and raises `PinMismatchError` on skew (an
  in-repo deliberate-bump tripwire); forced-mismatch negative tests.
- **SDLC oracle domain — baseline + MCTS, canary, κ-gate (F-013):** policy-injected specimens
  (a mandatory single-agent baseline control + MCTS) run a declared-N, deterministic SDLC suite
  judged by a pure property oracle (abstains on uninterpretable output). Outcomes are keyed by
  `(agent_version, domain)` with the task **excluded** from the key (`agent-core` 1.3.0 adds the
  additive `OutcomeRecord.agent_version`). **Brier reliability** (Murphy decomposition) is the
  primary metric; a discrimination canary separates a gold from a no-op agent by a Wilson-bounded
  pass-rate margin (not AUROC); the oracle **Cohen's-κ gate** validates over co-determinate pairs
  only and is power-aware. A seeded `MockPolicy` keeps every run offline and reproducible.
- **Honest holdout + confidence cross-check (F-014):** ReAct introduced as a *type-holdout* flow;
  a single-authority `HoldoutManager` reports instance-holdout (primary) and type-holdout
  (generalization) separately with an extrapolation caveat; the confidence cross-check ablates raw
  confidence against a flow-type indicator on a held-out partition with a seeded bootstrap-CI
  significance test.
- **Mutation engine + rotation (F-015):** a seeded mutation engine perturbs the suite into an
  instance distribution (preserving task identity and *not* re-keying the agent); a
  `RotationManager` gates on Brier-reliability stability across folds (undefined with <2 measurable
  folds).

### Changed
- **Hardening:** removed cross-package private coupling (a corpus-owned `flow_corpus.partition.bucket`
  replaces the private `agent_core.golden._bucket`); all behaviour-shaping values are config-/
  parameter-driven (`CorpusConfig.holdout_fit_fraction` / `bootstrap_resamples` / `bootstrap_alpha`,
  ReAct `confidence_threshold`, parameterised SDLC generator); the AURC discrimination metric is
  wired into `RunResult`.
- **Observability:** structured logging + `debug_span` instrumentation across the corpus (runner,
  rotation, cross-check, κ-gate, pinning, mutation), reusing `agent_core`'s public
  `get_logger`/`debug_span` (no new deps, no hardcoded levels).

### Fixed
- Corpus `OutcomeRecord`s are labeled `"corpus_oracle"` (not `HUMAN_AUDIT`), since the labels are
  oracle-derived, not an unbiased human sample — preventing contamination of `agent_core`'s
  auto-merge calibration if they ever reach its store.
- Rotation no longer reports a vacuous `stable=True` on a single measurable fold; the F-015
  identity-preservation check asserts the expected variant count first (no vacuous `all([])`).

### Notes
- `flow-protocol` 100% coverage; `flow-corpus` 100% coverage (gate ≥95); both strict-mypy + ruff
  clean across py3.10–3.12 via `.github/workflows/flow-corpus-ci.yml`. Property-based (Hypothesis)
  tests cover the pure functions.

### Quality & Eval-Integrity Gates

### Added
- **Calibrated auto-merge gate (F-010, opt-in / default-off):** a pure `agent_core`
  subsystem — `merge_gate.py` (deterministic `decide()`: mechanical-failure REJECT →
  protected-path ESCALATE → risk-derived `tau` + calibrator health + Wilson bin floor →
  AUTO_MERGE), `outcome_store.py` (append-only `OutcomeStore`, `BinningCalibrator`, and
  per-domain models built from HUMAN_AUDIT records on a held-out fold), `outcome_labeller.py`
  (passive revert/CI-failure/timeout-clean signals), `audit_sampler.py` (unbiased stratified
  sampling), and `merge_gate_ci.py` (CI entrypoint, exit codes 0/10/20, audit-logged
  decisions). Wired via `.github/workflows/calibrated-merge-gate.yml`, which auto-merges
  nothing unless `ENABLE_CALIBRATED_AUTOMERGE` is set. Documented in ADR 0005. Strict mypy +
  100% module coverage.
- **Real outcome detectors (F-010):** `outcome_labeller` wires real detectors instead of
  no-op placeholders — `agent_core/detectors.py`: `GitRevertDetector` (reads `git log` for
  the `This reverts commit <sha>` footer), `GitHubChecksFailureAttributor` (a commit's GitHub
  Actions check-runs via `gh api`), and `resolve_repo`. Every tunable lives on `DetectorConfig`
  (timeouts + failing-conclusion set); all subprocess calls are timeout-bounded and fail *safe*
  (missing binary / timeout / no repo → "no signal observed"). Shared `agent_core/timeutil.py`
  (`parse_iso8601`, Z-tolerant, UTC-default). Tests are mock-free — real temporary git
  repositories and real check-run payloads.

### Fixed
- **Calibrated merge gate (review follow-ups):** `calibrated-merge-gate.yml`'s decide step
  now fails on `REJECT` *and* on `merge_gate_ci`'s internal-error (`1`) / usage (`2`) exit
  codes — previously only `20` mapped to failure, so an error silently passed the gate.
  `OutcomeStore.all()` streams the append-only JSONL line-by-line instead of `read_text()`-ing
  the whole (unbounded) store into one string.
- **architecture-drift-guard:** `migrate_to_current` rejects a non-string
  `schema_version` (e.g. YAML list/dict) with a `ManifestError` instead of a bare
  `TypeError`; `_prepend_sys_path` now preserves manifest `sys_path` order on
  `sys.path` (was reversed by repeated `insert(0, …)`). (PR review follow-ups.)

### Changed
- **`validate_skill.py` (all copies):** the eval `setup` command's exit code is no
  longer ignored — a non-zero `setup` now fails the eval (with truncated
  stdout/stderr) instead of silently poisoning a passing run. Applied byte-identically
  to the canonical `scripts/validate_skill.py` and all three vendored skill copies.

### Added
- **Regression Gate (F-006):** `scripts/regression_gate.py` — materialises an isolated
  HEAD baseline via `git worktree` and blocks only *net-new* ruff/offline-test failures,
  complementing the absolute coverage gate. Line-keyed lint identity, robust class-based
  junit nodeid reconstruction, configurable lint/test paths + base ref + `block`/`warn`
  mode, and a JSON report validated by `scripts/regression_report.schema.json`.
- **Eval-Integrity Protected-Path Guard (F-007):** `scripts/eval_protected_paths.py`
  (single source of truth + glob matcher) and `scripts/check_protected_changes.py` CI
  guard, backed by `.github/CODEOWNERS`, require human approval (the `eval-change-approved`
  label) for any change to evaluation-defining files (features, config, gating, scorers,
  judges, validations, tests, CI).
- **Auto-Fix Loop — design-only, disabled (F-008):** `scripts/fix_loop.py` inert skeleton
  with a path-traversal-safe `ScopeGuard` that cannot write to protected paths, plus
  `docs/decisions/0004-auto-fix-loop.md` and the human enable-checklist.
- **Quality-Gates Workflow:** `.github/workflows/quality-gates.yml` runs feature
  validation, a dedicated ≥85% coverage gate for the new tooling, the regression gate
  (vs the PR base), and the protected-path guard.
- **Architecture Drift-Guard Skill (F-009):** `skills/architecture-drift-guard/` — a
  self-contained skill (runtime deps `grimp` + `pyyaml` only) that extracts a codebase's
  actual Python import graph, folds it to C4 **components**, and diffs it against a
  declared `architecture.yaml`. `scripts/drift_check.py` is the deterministic drift gate
  (with `--emit-actual` to bootstrap a manifest); `scripts/mermaid_gen.py` renders the C4
  diagram and `--check` enforces freshness. Reusable `scripts/adguard/` library with the
  grimp call isolated in `extractor.py`; ≥90% unit coverage plus structural+behavioral evals.
- **Architecture Dogfood Gate:** root `architecture.yaml` + `architecture.mmd` (seeded from
  `--emit-actual` and reviewed) and `.github/workflows/architecture-drift.yml`, a
  deterministic drift+freshness gate over `eval_harness` and `agent_core`. No model is in
  the gate's decision path.

### Changed
- **`.gitignore` / `.dockerignore`:** Ignore `regression_report.json`,
  `.regression_gate_junit.xml`, and the merge-gate runtime artifacts
  `merge_outcomes.jsonl` / `merge_decisions.jsonl`.
- **`tests/conftest.py`:** Expose `scripts/` on `sys.path` so tooling has first-class tests.
- **README / C4 Architecture:** Document the quality-gate and eval-integrity layer.
- **`skills CI` workflow:** Added an isolated `architecture-drift-guard` job (matrix
  3.10–3.12, pinned `grimp==3.14`) that never installs the repo packages.
- **`pyproject.toml`:** Added the pinned `archguard` optional extra used by the dogfood gate.

### Security
- Hardened `ScopeGuard` against path-traversal / absolute-path escapes (per peer review):
  writes are confined to the project root *and* outside the protected set.

## [1.1.0] — 2026-06-16

### Added
- **Skill Framework (F-003, F-004):** `scripts/validate_skill.py` tiered validation engine
  with structural + behavioral checks and `evals.json`-driven assertions.
- **OpenAI Judge Skill (F-004):** Full `skills/openai-judge/` skill with SKILL.md, eval
  fixtures, and a CLI runner supporting NVIDIA Nemotron & LM Studio backends.
- **Langfuse Tracing (F-005):** End-to-end Langfuse integration — `SDKLangfuseClient`,
  `observe()` decorator, `SafeLangfuseContext`, trace-to-dataset-item linking, and
  auto-wrapping of OpenAI client via `langfuse.openai`.
- **Spec-driven Development (F-001):** `validate.py`, `select_next.py`, `features.yaml`,
  `features.schema.json`, and per-feature validation scripts.
- **ADR Documents:** `0001-openai-compatible-judge.md`, `0002-skill-framework.md`,
  `0003-langfuse-integration.md`.
- **Snyk Integration:** Project registered for continuous dependency monitoring. `.snyk`
  policy file and `requirements.txt` manifest added.
- **`.dockerignore`:** Keeps container images lean.
- **C4 Architecture Diagram:** `docs/c4_architecture.md` — Mermaid-based context, container,
  and component views.

### Changed
- **`.gitignore`:** Expanded to cover `.coverage.*` shards, `.env` files, IDE artifacts,
  OS files, Snyk policy, and benchmark/output directories.
- **`README.md`:** Updated to reflect Langfuse, Snyk, OpenAI judge, and skill framework.
  Added architecture section, environment variable reference, and CI integration guide.
- **`pyproject.toml`:** Added `[tool.ruff]` and `[tool.mypy]` configuration sections.
  Added `ruff`, `mypy` to dev dependencies.

### Fixed
- **Security (CRITICAL):** Removed hardcoded Langfuse API keys from
  `langfuse_client/__init__.py`. Credentials are now sourced exclusively from
  environment variables or explicit kwargs.
- **Security:** Removed `pragma: no cover` from `SDKLangfuseClient` — the class is
  exercised by mocked tests and should contribute to coverage.
- **Testing:** Replaced `os.environ.clear()` in `test_langfuse_integration.py` with
  `monkeypatch` — fixes 24 cascading test failures on Windows due to destroyed
  `ComSpec` / `SystemRoot` variables.
- **Testing:** Rewrote `test_langfuse_integration.py` from `unittest.TestCase` to
  idiomatic `pytest` style with `monkeypatch` for environment isolation.
- **Config Loader:** Added `encoding="utf-8"` to `config/__init__.py` `load_config()`
  to fix silent encoding errors on Windows (`cp1252` default).
- **Logging:** Replaced f-string logger calls with lazy `%s` formatting in `judges/`
  and `langfuse_client/` to avoid unnecessary string interpolation.

### Security
- **Snyk Scan:** 9 dependency vulnerabilities identified (4 High in `urllib3`, 5 Medium).
  Documented in `CHANGELOG.md` and `requirements.txt` with minimum safe versions.

## [1.0.0] — 2026-06-15

### Added
- Initial release: spec-driven evaluation harness.
- Core modules: `engine.py`, `cli.py`, config loader with env interpolation and
  schema migrations.
- Component registries: scorers, datasets, targets, sinks, judges.
- Built-in scorers: `exact_match`, `regex_match`, `contains`, `json_keys`, `llm_judge`.
- Built-in datasets: `inline`, `jsonl`, `langfuse`.
- Built-in targets: `echo`, `callable` (dynamic import).
- Built-in sinks: `console`, `json_file`, `langfuse`.
- Built-in judges: `mock`, `bedrock`, `openai`.
- Quality gating with configurable rules.
- Entry-point plugin discovery.
- ~96% test coverage, 86 tests.
