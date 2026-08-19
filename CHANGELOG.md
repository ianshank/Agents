# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.3.0-dev] — Unreleased

### Added — judge bias calibration: order, verbosity and self-preference probes (F-057)
- **Bias probes** — new `agent_core/judge_calibration.py`: `order_flip_rate` (grades a pair in
  both answer orders and reports the disagreement/preference-shift rate), `verbosity_preference_delta`
  (deviation from 50/50 among semantically-equivalent concise/expanded pairs, symmetric — a judge
  that penalises length is biased too, not just one that rewards it), and `self_preference_breakdown`
  (win-rate broken down by whether the winner shares the judge's model family). All three reuse the
  existing `wilson_interval` for their confidence intervals; a new `ProbeConfig` (frozen dataclass,
  registered in `FrameworkConfig` like every sibling `*Config`) carries every tolerance — no numeric
  literals at call sites. `ProbeConfig.min_pairs` is enforced in all three: a probe whose
  informative-pair count falls below it fails (with a `degenerate` reason naming the shortfall)
  even when the measured rate already clears its own tolerance, mirroring
  `agent_core.calibration.evaluate_calibration`'s own sample-size floor.
- **Pairwise calibration corpus** — new `agent_core/pairwise.py`: `PairwiseItem` /
  `PairwiseSet` (not `GoldenItem`/`GoldenSet`, which are binary-label with no pair concept), with
  known-equal / clearly-better / clearly-worse canaries cross-validated against their own expected
  verdict at construction — an internally-inconsistent canary is a corpus-authoring bug caught
  immediately, not silently scored wrong later.
- **`JudgeCalibrationReport`** — new `agent_core/judge_calibration_report.py`: versioned,
  composes agreement, Cohen's κ (via a new standalone `agent_core.golden.percent_agreement`), every
  bias probe and canary pass rate into a `may_gate` verdict and a `failing_checks` tuple naming
  every currently-failing check, not just the first. Canary results are diagnostic only — spec
  names agreement, power and the three bias tolerances as the gating conditions, not canaries.
- **Programmatic scorers ordered ahead of judges** — `Scorer` gains `uses_judge()` (a plain
  method, not a `@property`, mirroring `TargetRunner.is_deterministic()`'s reasoning); the engine
  stable-sorts scorers on it and skips a judge entirely — no `ScoreResult` recorded — once a
  programmatic scorer has already failed the item, so a judge's verdict can never convert that item
  into a pass. Deliberately does not record a synthetic placeholder score for the skip: that would
  silently pollute the judge's aggregate mean and `reliability.py`'s per-scorer quantiles with a
  number that was never actually judged.
- **Gating requires a named calibration artifact** — new `JudgeCalibrationGateConfig`
  (`calibration_artifact_id`, required, non-empty) on `EvalConfig`; `eval_harness.gating.
  require_calibration_for_judge_gating` rejects a gate rule that targets a judge-backed scorer
  (checked against the real, constructed `Scorer`'s resolved name/`uses_judge()`, not guessed from
  raw config) with no named artifact. `eval_harness.agent_core_adapter.require_report_to_gate`
  then enforces a real `JudgeCalibrationReport` against that name: the report's `artifact_id` must
  match, and it must actually authorise gating (`may_gate`), with every failing check named in the
  error — alongside its `degenerate` reason when the failure is an undersized probe rather than a
  genuine bias, so the two don't look identical in the one message a human or CI log actually sees.
- **`behavioral_regression` wiring** — new `build_judge_calibration_report`, exported alongside
  `validate_judge`, composing `validate_judge`'s own `KappaReport` (agreement, κ, power) and
  `agent_core.golden.percent_agreement` over the same codeterminate pairs with pre-computed bias
  probes into a full report — the three probes come from a separate pairwise corpus this function
  does not itself run.
- Landed as F-057 (`openspec/changes/extend-judge-calibration/`, ADR 0031), the third of five
  ordered changes from `docs/plans/agent-eval-coverage/PLAN.md` (F-051, F-056 came first). No new
  `architecture.yaml` component edge — `agent_core` cannot import `flow_corpus` (the airgap holds;
  agreement is computed by `behavioral_regression`, which already depends on both, not by
  `agent_core` itself). Full proof: `python scripts/validations/F_057.py`.

### Added — repeated-attempt reliability metrics: `pass@k` / `pass^k` (F-056)
- **`run.repetitions`** — a new, optional `RunSettings` field (`ge=1`, default `1`) that expands
  each selected item into `k` independent `target.run(item)` calls through the full scorer
  lifecycle, in both the sequential and parallel dispatch paths, retaining every raw attempt
  before any aggregate is computed. Default `1` reproduces the exact pre-change engine behaviour
  — the sequential path's single continuously-advancing RNG, one `ItemResult` per item, no new
  serialized keys — verified byte-identical by test, not just by inspection.
- **Attempt identity** — `ItemResult` gains `attempt_index` / `attempt_id` / `item_run_id`,
  appended last and emitted from `RunResult.to_dict()` only when set (mirrors the `trajectory`
  precedent, ADR 0031).
- **The scorer RNG is reset every attempt** — each attempt gets `RunContext.rng` freshly
  constructed from the item's own seed, never advanced across attempts of the same item, so a
  scorer that draws from `ctx.rng` cannot manufacture cross-attempt flakiness that would be
  misread as agent unreliability. `TargetRunner` gains an optional `is_deterministic()` method
  (a plain method, not a `@property` — a `runtime_checkable` Protocol's `issubclass()` support
  requires every member to be callable); `ModelTarget` derives it from `temperature == 0.0`.
- **`deterministic_sampling` diagnostic** — a new `RunResult.diagnostics` field carries the
  caveat *"`pass^k` is 1.0 because sampling is deterministic, not because the agent is
  reliable"* when an item's `pass^k` is 1.0 only because the target is declared, derived, or
  observed deterministic (ADR 0029's vacuous-pass lesson); omitted entirely when empty.
- **`ReliabilityAggregator`** — a new, pure `src/eval_harness/reliability.py` (no I/O, clock or
  RNG) computing per `(item, scorer)`: success count, empirical pass rate, `pass@k` (at least one
  of `k` attempts passes) and `pass^k` (all `k` attempts pass) as booleans, score quantiles over
  every attempt, and latency/cost quantiles scoped to successful attempts only. `pass^k` is
  aggregated strictly per item and never pooled across items — a suite of easy items cannot mask
  one that fails half the time.
- **Gating** — `GateRule.metric` accepts `pass_at_k` / `pass_power_k`, wired into
  `evaluate_gate()` as the fraction of items whose own per-item boolean is `True`, computed
  lazily and at most once per gate call (never eagerly on every run, and never re-derived from
  pooled raw attempts).
- **Config strictness** — `EvalConfig` now rejects an unknown top-level key (`extra="forbid"`),
  closing a real gap found while implementing this change: a `gates:` typo of the real `gate:`
  field was previously silently ignored rather than raising.
- Landed as F-056 (`openspec/changes/add-repeat-reliability-metrics/`, ADR 0031), the second of
  five ordered changes from `docs/plans/agent-eval-coverage/PLAN.md` (F-051 was the first). Full
  proof: `python scripts/validations/F_056.py`; end-to-end: `PIPELINES["repeated_attempts"]` in
  `tests/test_matrix_eval_tools.py`.

### Docs — ledger refresh: archive 6 landed OpenSpec proposals, correct 5 stale claims
- **Archived `harden-quality-gate-integrity` (F-054), `add-eval-matrix-completeness` (F-053),
  `pin-lockstep-tool-versions` (F-055), `test-skill-validator-library`,
  `add-openspec-implementation-review`, and `add-foundation-reviewer-charters`** — all six
  shipped weeks ago but sat under `openspec/changes/` marked `proposed`, one
  (`add-foundation-reviewer-charters/proposal.md`) self-contradicting its own shipped work
  ("no spec-guardian/peer-reviewer charter exists"). Moved to `changes/archive/`, `Status:`
  flipped to `implemented`, `openspec/README.md`'s index updated (verified against
  `docs.yml`'s own guard script: 6 in flight, 10 archived). Broke two things downstream, both
  fixed in the same pass: `skills/openspec-implementation-review`'s `prompts.py` hardcoded
  `PRECEDENT_REVIEW`/`SECOND_PRECEDENT_REVIEW` at the old paths (used to build its own dispatch
  prompts) and `tests/test_validate.py` had two tests asserting against the old paths directly
  — both repointed at `changes/archive/...`, full suite re-verified green (113 passed).
- **Corrected 5 stale "still open" claims in `NEXT_STEPS.md`** — the `Scorer`→`typing.Protocol`
  migration (`d4dc07f`) and merge-gate tech-debt items G4/G6/G8/G9 (`9d68d44`, `38761f7a`) were
  all already fixed but still listed as pending; the "extend `openspec-peer-review` with the
  two-pass protocol" TODO was already shipped (v1.1.0); `claude-foundation`'s subagent count
  was still recorded as 2, not the current 4 (`explorer`, `test-runner`, `spec-guardian`,
  `peer-reviewer`).
- **`docs/CHARTER.md` had the same `Scorer`/`abc.ABC` claim stale** — its "Dependency injection
  via Protocol" section still said the conversion was "not yet done"; corrected to state all
  five core interfaces are `typing.Protocol` as of `d4dc07f`.
- **Minor drift closed alongside:** `skills/common/SKILL.md` said "11 skills" (actually 13);
  `skills/architecture-drift-guard/SKILL.md` was missing `validator_version: '2.0'`, a gap
  ADR 0017 had recorded but not fixed — now added, with an errata note in the ADR.

### Fixed — skills-ci.yml `common` job: coverage gate silently measured 0%
- `python -m pytest tests --cov=skill_validator ...` (a bare module name) resolved against
  `sys.modules`, not a file path — and `skill_validator` was already cached there (directly via
  the test file's own `import skill_validator`, and via `common/__init__.py`'s re-export under
  the qualified name `common.skill_validator`) before pytest-cov's tracer attached. Every run
  reported `Total coverage: 0.00%` and failed the `--cov-fail-under=95` gate regardless of test
  quality — found while merging an independent, unrelated PR's own new test suite for the same
  module and empirically confirmed against *both* suites, ruling out a test-content cause.
  `--cov=.` (path-based, sidesteps module-name resolution entirely) plus a new
  `skills/common/.coveragerc` (`omit = tests/*`) restores the original intent — the 95% floor
  scoped to exactly `skill_validator.py` + `__init__.py` — verified clean at 100%/72 passed.

### Fixed — quality-gate: coverage-threshold and PYTEST_ADDOPTS env-override evasion closed (F-054)
- **`COV_FAIL_UNDER` and single-source `COVERAGE_SOURCE` were live, unguarded environment
  overrides.** `COV_FAIL_UNDER=0 ./scripts/quality-gate.sh coverage` made every generated
  package's coverage gate trivially pass — the generated script never `unset` anything and
  never warned. `skills/quality-gate/scripts/gategen/render.py`'s `_coverage_command()` now
  interpolates both as generation-time literals (`--cov-fail-under=95`, `--cov="demo"`) in
  both the single- and multi-source branches, and unconditionally warns to stderr
  (`quality-gate: COV_FAIL_UNDER is ignored; ...`) when either is set anyway — exit code
  unaffected either way. `_variables()` no longer declares either as an overridable shell
  variable.
- **`PYTEST_ADDOPTS` passed through to pytest completely unguarded.** A coverage-weakening
  flag (`--no-cov`, `-k`, `--override-ini`) set in the environment silently applied to every
  pytest invocation the gate made. A new `_pytest_addopts_guard()` warns then `unset`s it
  ahead of every pytest call the generated script makes (`do_test`, `do_coverage`); root
  `scripts/quality-gate.sh`'s hand-maintained `do_extra()` (below the marker, out of the
  generator's reach) carries the identical guard by hand.
- **Coverage-exclude regex was unanchored in 4 packages, contradicting ADR 0009's own
  "aligned" claim.** `agent-core`, `behavioral-regression`, `flow-protocol`, and
  `flow-corpus`'s `pyproject.toml` `exclude_also` used `"\.\.\."` (matches ANY line
  containing three dots — `coverage.py` uses `re.search`, not a full-line match) instead of
  the anchored `"^\s*\.\.\.$"` root `pyproject.toml`/`scripts/.coveragerc` already used.
  Corrected in all four; each package's full test suite was re-run for real afterward and
  stayed clear of its floor (`agent-core` 98.49%/95%, `behavioral-regression` 100%/95%,
  `flow-corpus` 100%/95%, `flow-protocol` 100%/95% — the anchored pattern's removal of the
  one-line `Protocol`-stub exclusion does not regress coverage; verified, not assumed).
  `docs/decisions/0009-tech-debt-audit-and-compat-surface.md` carries an Errata recording the
  correction (factual, no superseding ADR).
- **`tests/_e2e_matrix.py`'s `_floor_from_gate_script`** updated to match the new
  `--cov-fail-under=N` literal form; the real cross-package floor-agreement check
  (`test_floor_anchors_agree_with_each_other`) was re-verified to still compare two
  independent anchors per package, not one silently left unmatched.
- All 7 generated `scripts/quality-gate.sh` copies regenerated (root, `agent-core/`,
  `behavioral-regression/`, `claude-foundation/`, `experiments/backend-validation/`,
  `flow-corpus/`, `flow-protocol/`); the frozen `skills/project-setup` eval fixture is
  untouched. New subprocess-level positive-control tests
  (`skills/quality-gate/tests/test_coverage_gate_integrity.py`) run the real rendered gate
  against a real under/over-covered fixture and confirm all evasions above stay closed —
  nothing here is mocked. `quality-gate` skill bumped `1.1.0` → `1.2.0`. New
  `scripts/validations/F_054.py`, `features.yaml` F-054. Full design and the branch-coverage
  regex-safety experiment: `openspec/changes/harden-quality-gate-integrity/design.md`.

### Added — tool-version lockstep gate (F-055, ADR 0034)
- **`ruff==0.15.20`/`mypy==2.1.0` are now checked, not just commented, across every copy.**
  The pins are hand-duplicated — each carrying a "bump deliberately, in lockstep" comment
  but no automated check — across the `dev` extra of 7 `pyproject.toml` files (root,
  `agent-core`, `behavioral-regression`, `flow-protocol`, `flow-corpus`,
  `claude-foundation`, `experiments/backend-validation`) and every `pip install` line in
  `.github/workflows/skills-ci.yml`'s per-skill jobs. New `scripts/tool_versions.py` is the
  single source of truth; new `scripts/validations/F_055.py` (read-only — no installs, no
  subprocess, no edits to `skills-ci.yml`) asserts every occurrence matches it exactly, and
  fails if a pin is dropped entirely, not just mistyped. Full CI templating of the
  install lines was considered and explicitly deferred (ADR 0034) as a separate, larger
  follow-on. `AGENTS.md`'s existing pin bullet now points at `scripts/tool_versions.py`.
- **`agent-core/.pre-commit-config.yaml`'s `ruff-pre-commit` pin was drifted at `v0.8.0`** —
  live, contributor-facing, and the exact version ADR 0034's own Context section cites as the
  historical incident that motivated this change. Bumped to `v0.15.20`; not covered by
  `F_055.py` (different YAML shape than the `tool==version` regex it matches), noted in the
  ADR as a known, separately-tracked surface.

### Added — backend-validation: full Opik matrix coverage + air-gap P4 (PR #147)
- **Air-gap phase P4 exists now (`experiments/backend-validation/`).** `make airgap` and
  `make status` invoked CLI subcommands that did not exist (argparse exit 2); no compose
  had an internal network, no DNS witness ran, and the prober Dockerfile was built by
  nothing. New `airgap_phase.py` orchestrates the dual-scored egress-blocked L1 re-run
  through injectable seams (`AirgapIO` + `CommandRunner`): per-backend `internal: true`
  overlay networks with a CoreDNS witness that logs every query and resolves nothing, a
  witness-liveness **canary lookup** (Docker's embedded DNS answers service names locally,
  so a *clean* opt-out run would otherwise leave the witness log empty and unprovable), a
  strict iptables-counter contract (an integer only on positively identifying THIS run's
  bridge DROP counter — anything ambiguous degrades to witness-only rather than
  manufacturing a trustworthy zero), and prober exit-code gates (rc 4 propagates HALT;
  any failure makes the observation unusable — a broken probe run can never confirm an
  air gap). `all --with-airgap` opts the chain in; the default chain is byte-identical.
- **Opik guardrails stack + the nginx conf the frontend always needed.** The official
  `opik-frontend` image bakes in NO nginx conf (the official compose volume-mounts one);
  our stack mounted nothing, so nothing ever listened on 5173 and the committed Opik
  stack could not serve its published port at all. The guardrails-flavor conf is now
  committed and mounted read-only; the `guardrails` service (the one matrix cell where
  Opik claims ● with Langfuse as the negative control), the official python-backend
  healthcheck, `PYTHON_EVALUATOR_URL`, and `TOGGLE_GUARDRAILS_ENABLED` are wired per the
  fetched 1.7.26 sources. Ops-burden metrics will shift: the guardrails image is multi-GB.
- **Judge stack deploys, and server-side evaluators can actually reach it.** `run_deploy`
  now deploys the judge compose (project `bv-judge`) and pulls `${BV_JUDGE_MODEL}`; a
  shared external `bv-judge-net` network (ensure-created first, `bv-judge` alias on the
  ollama service) replaces the unreachable host-gateway design — the judge publishes on
  the host's 127.0.0.1 only, which containers can never reach (Copilot review catch).
  Air-gap overlays `!override` the network list on the attached services because compose
  UNIONS explicit network lists on merge (and `!reset [value]` drops the value) — both
  verified against `docker compose config`.
- **Every deploy image is digest-pinned.** All 14 refs (bases, overlays, prober FROM)
  resolved via the registry manifest API and recorded in `deploy/DIGESTS.md`;
  `pin-digests` now also reaches `compose.airgap.yaml` files and Dockerfile `FROM` lines.

### Fixed — backend-validation: five evidence-integrity defects in the Opik client
- **The L1 Opik client could corrupt matrix evidence in every direction.** No
  workspace/`Comet-Workspace` was sent anywhere; `fetch_otel_trace` fetched by the raw
  32-hex OTLP id — a guaranteed miss reading as a false *absent*; `rollback_prompt` read
  a payload key the probe never sends and silently "succeeded" on the latest version — a
  false *positive*; `link_dataset_run` was a GET pretending to be a write (always-200
  false positive); judge/RAG/guardrails/annotation/alerts ops posted guessed shapes to
  wrong routes. Every op is rebuilt on surfaces verified against the extracted `opik`
  wheels (1.11.14 and 1.7.26): OTel verification searches a unique span marker; rollback
  recreates and verifies the target text; experiment linking creates a real experiment +
  item references; RAG metrics run the SDK's own `AnswerRelevance` against the local
  judge (emitting the `score=` token the rubric's range predicate parses); guardrails
  validation posts through the frontend's `/guardrails/` proxy exactly as the SDK does;
  judge configuration registers the local judge as a `custom-llm` provider and arms a
  100%-sampling online rule, so `run_judge_eval` exercises the platform's real trigger
  (a fresh trace in the armed project). Every SDK touch is a guarded chain with an
  honest-`error` fallback, version-tolerant across the committed 1.7↔1.11 SDK/stack skew.
- **The air-gap dual-scoring levers were dead.** `config.yaml` stored container-variable
  names (`TELEMETRY_ENABLED`, `OPIK_USAGE_REPORT_ENABLED`) but the compose files
  interpolate `${BV_LANGFUSE_TELEMETRY}` / `${BV_OPIK_USAGE_REPORT}` — the opt-out run's
  env was a silent no-op, poisoning any future P4 comparison.
- **`.env.example` omitted most `:?`-required compose secrets**, so the documented first
  `make deploy` failed before compose could even render; it now lists every required
  placeholder plus the new workspace/host/judge knobs.

### Docs
- **OpenSpec change proposal: `add-panel-judge`
  (`openspec/changes/add-panel-judge/`).** Proposes a `panel` judge — one registered
  component fanning an evaluation out to N member judges and aggregating under an explicit
  strategy (`median`/`mean`/`majority`), with disagreement surfaced in `JudgeVerdict.raw`
  and abstention above a configured spread instead of a synthetic consensus. The package
  specifies per-member budget accounting (a naive panel under-charges `judge_budget` and the
  F-030 rate window by factor N, because `BudgetedJudge` reserves once per `evaluate()`) and
  the calibration obligations — panel-level κ, pairwise member-redundancy κ, reported
  abstention rate, named-artifact gating — that keep a panel advisory until it earns trust.
  Ships as a reviewed proposal only: no code, config, or protected paths change.

### Fixed — two guards that did not do what they appeared to do
- **`BudgetedJudge.attach_client` was unreachable from the engine.** `from_config`
  injected the Langfuse client into `[dataset, judge, *sinks]` and only *then* replaced
  `judge` with the `BudgetedJudge` wrapper, so the wrapper's delegating `attach_client` was
  never invoked on the only path that constructs it — while `agent_core_adapter` reported
  **100% coverage**, because a unit test called the method directly. Tested, and
  production-unreachable: the same false-green shape as F-052's dead `--cov=` targets and
  F-053's never-run parquet cells. Tracing was not broken, but only by accident —
  `OpenAIJudge.attach_client` mutates its own client, so attaching to the raw judge
  happened to survive the swap; a wrapper holding client state of its own, or a judge that
  builds members lazily, would have been silently skipped. The wrap now precedes injection,
  which is behaviour-identical for every existing judge (the wrapper delegates inward) and
  makes the delegation live. The regression test spies on the **wrapper**, not the inner
  judge: an inner-only assertion passes under the old ordering too — verified by
  re-introducing it — which is exactly how the gap survived.
- **`check_size_budget.py` failed locally on generated artifacts CI never sees.** The walk
  prunes by directory name and does not consult gitignore, so `.skill-validation/` — the
  fixture repos `validate_skill.py --tier behavioral` materialises, which deliberately
  contain over-long files — was scanned and hard-failed the gate. Running the *documented*
  local sequence (behavioral validation, then the size budget) therefore produced a failure
  that CI cannot reproduce, because CI runs the two in separate jobs with fresh checkouts.
  `.skill-validation` now sits in `EXCLUDED_DIR_NAMES` beside `build`, `dist` and
  `.pytest_cache`, the same category of generated directory.

### Fixed — `repo-invariant-review` predicted the protected-path guard with an approximation of it
- **The skill now loads the repo's own `is_protected` instead of re-deriving it.**
  `check_invariants.py` scraped `PROTECTED_PATTERNS` out of
  `scripts/eval_protected_paths.py` with a regex and then matched with its own prefix
  matcher, which stripped glob metacharacters down to a directory prefix. That is not
  equivalent to the real matcher, and it fails in the dangerous direction: a mid-path
  wildcard such as `skills/*/tests/**` strips to `/tests` and matches **nothing**, so the
  skill would report "no protected files changed" for a change CI still blocks — a false
  negative from the tool whose entire job is predicting that block. It now imports the
  guard's own `is_protected` (the single-sourcing principle `check_guard_reachability.py`
  states about the pattern list, applied to the matching logic too), falling back to the
  documented prefix behaviour only when the module is absent, unloadable, or predates
  `is_protected`. Loading runs under `sys.dont_write_bytecode` so executing the guard
  cannot write `__pycache__` into the tree under review — that leaked into `git status`,
  then into `changed_files`, and broke the skill's own byte-stability postcondition on the
  second run.
- **`SKILL.md` documented a validation gate that ran nothing.** It instructed
  `validate_skill.py --skill . --tier standard`; the validator only branches on
  `structural` and `behavioral`, and an unrecognised tier is not an error — it matches no
  branch and exits 0. The skill whose stated purpose is having "a real gate" documented a
  vacuous one, while CI ran the correct tiers, so the divergence was invisible. Audited
  every other skill's `SKILL.md`: this was the only offender.
- **`skills/README.md`'s registered-skills table was stale**, omitting `repo-invariant-review`
  and `common` — both registered in `marketplace.yaml` and present on disk. Nothing compares
  the table to the registry, which is why it drifted; the table is corrected and `common` is
  now described as the shared library it is rather than left unexplained.

### Added
- **Generated end-to-end test matrix (`docs/e2e-matrix/`, `tests/_e2e_matrix.py`).** A full
  `run_all_e2e.ps1` run now renders to a reviewable artifact: markdown, one CSV per sheet,
  and an optional `.xlsx` workbook (new pinned extra `e2e-matrix = ["openpyxl==3.1.5"]`,
  kept out of `dev`). Five sheets — test matrix, summary, coverage grid, credentials,
  provenance. Nothing is restated in the generator: the step inventory is parsed from the
  runner, results from `summary.json` and the per-suite JUnit XML, coverage floors from each
  unit's `pyproject.toml`/`quality-gate.sh`/`.coveragerc`, live-step credentials from the
  smokes' own declarations and `$liveJudges`, so a step added to the runner appears with no
  code change and a step in a report that the parser cannot see is a hard error. The render
  is byte-reproducible — `openpyxl` stamps `dcterms:created`/`modified` with the wall clock
  and `zipfile` stamps each archive entry, and both are pinned to the run's provenance
  timestamp — and freshness-gated by `tests/test_e2e_matrix.py --check` wherever a run report
  exists. Rationale and the amendment to ADR 0032 in
  [ADR 0033](docs/decisions/0033-generated-e2e-matrix-workbook.md).

- **Docs: Claude Code ecosystem research (`docs/claude-code-ecosystem-research.md`).**
  Survey of the seven ecosystem repos popularized by the "7 GitHub Repos That Made Me
  Addicted to Building with Claude AI" article — repomix, the MCP reference servers,
  claude-mem, claude-hud, claude-context, rtk, and awesome-claude-code — verified against
  live GitHub/npm sources on 2026-08-08. Each repo gets an adoption verdict against the
  repo's reversible-adoption / offline-determinism doctrine, concrete integration points
  (claude-foundation plugin, `skills/marketplace.yaml`, harness registries, CI gates), and
  a P1–P3 incorporation roadmap; notable finding: an independent JetBrains benchmark
  contradicts rtk's headline token-savings claim, so rtk is routed through a model-bench
  paired-trial measurement rather than adopted on reputation. Indexed in `docs/README.md`
  and the mkdocs nav.

### Fixed
- **The generated e2e matrix asserted values that were not true.** A gap analysis of the
  merged artifact found the generator guessing facts `run_all_e2e.ps1` already declares:
  `e2e:skills+hooks` shipped blank test counts because its JUnit file (`e2e_journeys.xml`)
  could never match a stem guessed from the step name; the Workdir column claimed `.` for
  `e2e:backend-validation`, which actually runs in `experiments/backend-validation`; the
  Command column dropped every non-quoted token, rendering `compare --config` with no value;
  and an all-errored suite read as clean because JUnit `errors` was parsed and never shown.
  All four are now read from the runner's own declarations, and a path that cannot be
  resolved renders blank rather than guessed. Guards were tightened alongside: the freshness
  check now covers the CSV mirrors (Provenance exempted on both sides), `--update` and the
  freshness test share one builder so redaction cannot make an artifact permanently "stale",
  the exit-code contract is a typed `MatrixConfigError` instead of a substring match on the
  message text, and `scripts/e2e_shims/sitecustomize.py` finally has a test — it is never
  imported, so it does not even appear in the `--cov=scripts` report. The smoke-module to
  step-name table is gone: credentials come from the `Test-EnvSet` gate guarding each live
  step. Coverage 90% -> 99% and 96% -> 98%, zero missed statements, with a dedicated CI
  floor so the modules are no longer absorbed by a ~40-module aggregate.

  **Third hardening pass (same PR).** A follow-up gap analysis, verified against the real
  code and the real runner rather than an agent's say-so, closed cross-sheet drift and
  silent data loss the first two passes left standing. `policy_problems` now catches a step
  observed under the wrong tier and a duplicate step name in the run report — either
  previously left the Test Matrix and Summary sheets silently disagreeing. `load_junit`
  matches `<testsuite>` by local tag name (a namespaced file previously matched nothing) and
  now warns and omits a file with zero `testsuite` elements instead of recording a truthy,
  wrong `"0"`. `derive_workflows` now attributes `quality-gates.yml` to the root unit — the
  very workflow that runs this generator's own coverage floor was invisible to it — and
  `derive_packages` discovers experiment manifests recursively rather than only direct
  children of `experiments/`. Every file read for "does this exist and is it readable" now
  goes through one helper that also catches `UnicodeDecodeError`, previously an uncaught
  `ValueError` subclass that escaped as a raw traceback instead of the documented
  `MatrixConfigError`. `generated_at` is normalized to UTC once, at the source, before it
  reaches either the Provenance sheet or the workbook's pinned timestamps — the committed
  artifact's "Generated at (UTC)" row had carried the committer's raw local offset.
  `_call_details` now reads `Invoke-CmdStep`'s third positional (`SkipCodes`) correctly
  instead of assuming every verb shares `Invoke-PytestStep`'s `(WorkDir, Junit)` signature.
  An empty resolved `$suites`/`$liveJudges` array body now warns instead of silently
  producing zero steps; `stale_csv_mirrors` now also sweeps the CSV directory for orphans
  left behind by a renamed sheet; `freshness_failure_message`'s `sheets=()` default — which
  could report "the markdown is stale" for what was actually a CSV-only drift — is gone.
  Hard-coded duplication closed: new constants for the status vocabulary, the
  `summary.json`/workbook filenames, the smokes directory, the runner's relative path and
  the regeneration command, each previously respelled at 2–6 call sites; `build_sheets
  (root=...)` now derives the runner path from `root` instead of a module global. Redaction-
  unavailable now warns instead of silently shipping unredacted output in a committed file.
  Added `make e2e-matrix-check`/`e2e-matrix-update`, mirroring the existing
  `matrix-check`/`-update` pair. Caught two defects in the pass itself before they shipped:
  `datetime.fromisoformat` only accepts a trailing `Z` from Python 3.11, so a CI git for a
  committer in the UTC zone crashed the module on this repo's 3.10 floor until normalized by
  hand; and an early version of the workbook byte-reproducibility test compared against the
  *committed* `.xlsx`, which is unstable by construction (its pinned timestamp is derived
  from the commit that carries it, so the next `git log` can never reproduce it) — replaced
  with a test that regenerates the real report's sheets twice under a fixed provenance and
  compares those two outputs to each other. 94 tests (11 new), 99.22% coverage on the two
  modules.
- **The e2e interpreter shim printed a breadcrumb into every child process off Windows.**
  `scripts/e2e_shims/sitecustomize.py` warned whenever `platform._wmi_query` was absent — but
  that symbol only ever exists on Windows, so on Linux the message went to the stderr of
  *every* interpreter started with the shim on `PYTHONPATH`, i.e. every step of a run. It
  polluted each step log and broke `test_cli_version`, which asserts a subprocess prints the
  version string and nothing else; that failure took down both `suite:root` and
  `suite:scripts-gate`. The breadcrumb is now Windows-only, where the WMI hang it diagnoses
  can actually occur.
- **`live:judge-bedrock` could never have passed.** The runner emitted
  `judge.params.model` for all three live judges, but `BedrockJudge.__init__` takes
  `model_id` (only `OpenAIJudge`/`AnthropicJudge` take `model`), so the step raised
  `TypeError: unexpected keyword argument 'model'` the first time it actually executed. It
  had only ever SKIPped for want of AWS credentials, so the mismatch stayed invisible — the
  same false-green shape as the D-1/D-2 Tier-D defects. The keyword is now declared per judge
  in `$liveJudges`, and `tests/test_e2e_matrix.py` checks each declared keyword against the
  real constructor signature so signature drift fails in the test suite rather than in
  Tier D.
- **`phoenix_smoke` printed the collector endpoint unredacted.** The redaction pass that
  introduced `_smoke_lib.safe_endpoint` hardened `langfuse_smoke` but not its sibling, so
  `PHOENIX_COLLECTOR_ENDPOINT` was echoed verbatim on three paths (the success line, the
  `configure_tracing`-returned-`None` failure, and the incomplete-drain failure) plus the
  unparseable-URL branch. An endpoint carrying a credential in userinfo
  (`https://user:key@host`) or a query (`?api_key=…`) therefore landed in
  `artifacts/e2e-report/*.log` — which is copied around and quoted into PRs, and which the
  CI-only gitleaks scan never reads. All four now go through `safe_endpoint` (scheme/host/
  port only), except the unparseable branch, which has no host to keep and so names
  `PHOENIX_COLLECTOR_ENDPOINT` rather than echoing its value. `TestCredentialRedaction`
  covers each path independently and each case was confirmed to fail against the unfixed
  script; the tests also assert the host still appears, so a redaction that blanked the
  whole diagnostic could not pass them. Also drops a literal `80` that restated
  `DEFAULT_PORTS["http"]`, and corrects two `run_all_e2e.ps1` comments that pointed at a
  non-existent `tests/test_smoke_tools.py` and claimed the smokes live in `tools/`.
- **Tier D of the e2e runner could not pass, and could not report that it could not
  pass.** Three compounding defects, all invisible because every recorded baseline used
  `-Tiers offline`, which never executes Tier D. (1) The two smoke steps invoked
  `artifacts/langfuse_smoke.py` and `artifacts/phoenix_smoke.py`; neither exists at origin
  and `artifacts/` is gitignored, so they could not exist in any clone. (2) That was
  reported as SKIP rather than FAIL — a missing file makes python exit 2, and 2 was the
  declared skip code, making "this step is broken" indistinguishable from "no credentials
  configured". (3) The live journeys were themselves mocked: `judge: {type: mock}` returned
  a constant 0.9 and `target: {type: echo}` never called a model, so no live step ever
  performed a real round-trip. The smokes now live in tracked `scripts/smokes/` — inside
  the `--cov=scripts` floor, the `mypy scripts` target and the charter scan roots, rather
  than a top-level `tools/` that all three would have skipped — with 58 tests at 96–100%
  coverage and a shared `_smoke_lib.py`. The skip code is
  `78`/`EX_CONFIG` (which neither a missing file nor an `argparse` error can forge), a new
  `Test-StepScript` guard joins the runner's other anti-vacuous-pass checks, and
  `LOCAL_MODEL_ID` drives a real model target and judge against any OpenAI-compatible
  endpoint (falling back to echo+mock when unset). A full `-Tiers all` run is now
  36 PASS / 0 FAIL / 2 SKIP, the two skips being the cloud judges that need credentials.
- **Charter-invariants guard emitted OS-native path separators.**
  `check_magic_number_defaults` interpolated `path.relative_to(root)` directly, producing
  `flow-corpus\thing.py` on Windows — inconsistent with the `.as_posix()` used two functions
  away, and unmatched by any consumer keying on `/`. Separately, the test for
  `check_quality_gates_wired` still built its expectation with `str(tmp_path / …)` after the
  guard was changed to emit `.as_posix()` on 2026-08-06 (`6c507d8`). Both renderings are
  byte-identical on Linux, so the CI matrix — which is entirely `ubuntu-latest` — could not
  observe either bug.
- **Docs: eleven orphaned plan documents are now reachable.** `docs/README.md`'s "Plans"
  section described the `plans/<topic>/{PLAN.md,REVIEW.md}` convention but linked a single
  example, so a link-graph walk from the documented entry points (`README.md`, `AGENTS.md`,
  `docs/README.md`, the mkdocs nav) reached 53 of 64 `docs/**/*.md` files — eleven plan
  documents under `agent-eval-coverage`, `agent-record-decontamination`,
  `agents-critical-path`, `claude-foundation`, and `real-data-activation` were unreachable
  from anywhere. The section now carries a complete per-topic index; reachability is 64/64
  and the repo-wide broken-relative-link count (the advisory `docs.yml` `links` job) is 0.
  The research doc added in this release also gained 16 cross-links to the artifacts it
  names (`features.yaml`, `AGENTS.md`, the marketplace, the foundation plugin, ADR 0009,
  `session_logger.py`) per `docs/STYLE.md`'s relative-cross-link rule; these resolve on
  GitHub and raise the known non-strict `mkdocs build` warning count for outside-`docs_dir`
  targets from 52 to 65 (the accepted pattern `docs/CHARTER.md` already follows — see the
  note in `mkdocs.yml`).
- **Docs: factual corrections to the ecosystem research from an adversarial fact-check.** The
  research doc was re-verified claim-by-claim against primary sources after drafting. Two
  substantive errors were corrected: the archived MCP reference-server count was **14, not
  13** (and `git` exists in *both* the archived and live trees, so the proposed MCP-hygiene
  denylist must key on package name or it would reject the maintained Git server); and the
  JetBrains rtk benchmark's `+7.6%` cost result is scoped to **low reasoning effort** — the
  effect is flat/zero at high effort, across 425 billed trials — so the P1 replication now
  requires stratifying by reasoning effort rather than pooling, which would have averaged
  away the deciding variable. Also corrected: claude-hud writes private-permission cache
  files (it is not "zero storage"); `modelcontextprotocol/servers` is tri-licensed
  (Apache-2.0 new code/spec, MIT un-relicensed legacy, CC-BY-4.0 docs, reported
  `NOASSERTION`) and is maintained by the MCP steering group rather than Anthropic;
  claude-mem's cloud tier is CMEM Cloud/CMEM Cloud Pro; and claude-mem's shipped
  `hooks.json` has no SessionEnd hook despite its README naming one. The Sources section now
  discloses which claims were corroborated via search snippets rather than direct fetch
  (the JetBrains post was egress-blocked) and flags the two claims that remain unverified.
- **Docs: the rtk benchmark proposal now isolates per-arm configuration state.** Review
  surfaced that `rtk init -g` is a *global* mutation (`~/.claude/hooks/rtk-rewrite.sh`,
  `~/.claude/RTK.md`, a `settings.json` hook entry, an `@RTK.md` reference in `CLAUDE.md`),
  so toggling install/uninstall in place between the rtk-on and rtk-off arms would leak hook
  state across the boundary and leave the next arm contaminated after any mid-run failure —
  silently invalidating the measurement the P1 item exists to produce. The proposal now
  requires a dedicated Claude configuration directory (or container) per arm, and notes that
  `--uninstall` leaves runtime artifacts under `~/.local/share/rtk/` so "uninstalled" is not
  "clean". Both documented package commands were also pinned to their reviewed versions
  (`@zilliz/claude-context-mcp@0.1.15`, `repomix@1.18.0`) instead of `@latest` and an
  uncopyable `<pinned>` placeholder, with the per-package token budget moved to config.
- **Matrix completeness: derived census, per-kind dim floors, generated coverage artifact
  (F-053, ADR 0032).** The declared test matrix (`tests/test_matrix_eval_tools.py`) was
  silently incomplete: the seven F-051 trajectory scorers had zero rows, `TestM7Registry`'s
  hand-maintained lists were stale, 13 registered aliases were asserted nowhere, and nothing
  failed when a new component registered rowless. Now the component census is derived from
  the live registries in a fresh subprocess (a sixth registry — the queued `STATE_ADAPTERS`
  — will be censused automatically and fail until it has rows and a policy entry), matrix
  classes carry literal `MATRIX_KIND`/`MATRIX_COMPONENTS` *checked declarations*
  cross-checked in both directions, per-kind dimension floors with a two-way-hygienic waiver
  map are enforced by `tests/test_matrix_coverage.py`, the alias→canonical pairing per kind
  is frozen by exact equality (`Registry._aliases` assignment has no duplicate guard — a
  repointed alias still resolves), M8 pipelines live in an importable `PIPELINES` index
  whose kinds are read from validated `EvalConfig` fields, and `docs/matrix-coverage.md` is
  generated (`python tests/test_matrix_coverage.py --update`) and freshness-gated. All
  seven trajectory scorers gained full matrix rows, and every sparse cell was filled to its
  kind's floor (judges/datasets/targets M2/M3/M6, scorers M3/M5/M6, sinks empty-run M2 +
  per-sink degrade/error M6, gating M6). Filling the rows surfaced shipped defects the old
  matrix had masked: `config/trajectory_eval.yaml` failed its own gate (reference arguments
  never matched the demo SUT; the covering test now runs it and asserts the gate PASSES);
  the braintrust dataset/sink matrix tests sat under an `importorskip` for an SDK CI never
  installs and could not have passed as written; `quality-gates.yml` carried a dead
  `--cov=F_052` — and the hardening pass below found more.

  **Hardening pass (same PR).** A two-agent peer review found the feature shipping its own
  defect class — coverage claims nothing verified. Three of the phoenix sink's floor cells
  asserted *nothing* (mutation-proven to pass against a gutted `emit()` and a factory that
  never degraded) while the artifact certified them; the cells now assert through the
  recording null clients both vendor sinks document as their test doubles. The parquet
  cells were a false green: gated on `pandas`, which no CI extra installs, every cell
  skipped in CI while the artifact claimed four — fixtures are now written with `pyarrow`
  (the reader's own dependency), and the whole class is mechanical rather than a review
  catch: `SKIP_GATED_IMPORTS` + `skip_gate_problems()` assert in both directions that every
  `importorskip` gate inside a matrix class is satisfied by the CI job's install line.
  `F_053.py`'s docstring claimed `--check` verified the floors "transitively"; it compares
  document text, so `--update` followed by the validator would have PASSed a holed matrix
  whose doc faithfully recorded the holes — the validator now evaluates the policy directly
  and `--update` refuses to write a holed artifact. The inverse of the dead-`--cov=` bug
  was live too (F_031/F_037/F_039/F_041/F_045 ran every build and were measured never);
  both directions are now closed by a drift test pinning the validator import list to the
  workflow's `--cov=` list. The guard library's own ~710 lines went from measured-by-nothing
  to a gated 95%; `_GRID_DIMS` and the dim-method regex now derive from `REQUIRED_DIMS` (a
  hardcoded grid omitted a column, so a genuinely missing cell rendered as *no* cell);
  markdown cell escaping stops a `|` in a waiver note from fabricating a column identically
  on both sides of the freshness comparison; and the guard gained convention-conforming
  logging including the CLI `basicConfig` without which its records were discarded at the
  root WARNING level — the G4 defect recreated in new code.
- **Agent trajectory evaluation (F-051, ADR 0031).** Every built-in scorer read
  `output.output` only, so an agent that returned plausible text by an invalid, wasteful,
  looping or policy-violating path scored identically to one that did the work. Langfuse
  tracing existed, but tracing is not scoring — spans are exported for human inspection and
  never enter a verdict. Adds immutable `ToolCallRecord` / `TrajectoryStep` /
  `AgentTrajectory` value objects and an optional `AgentTrajectory` appended **last** to
  `TargetOutput`, which stays mutable with its existing field order: freezing it or
  reordering its fields would break every mutation site and all positional construction.
  Capture is target-owned and Langfuse stays an export sink, so the offline path keeps its
  zero-network property. `core/_trajectory.py` is pure — tool-name and recursive argument
  canonicalisation with stable key ordering, a configurable ignored-field set for volatile
  values applied at any depth, and duplicate calls **preserved**, because duplicates are the
  precision and loop signal (matching is over multisets, not sets). Seven scorers register
  from the new `scorers/trajectory.py`: `trajectory_exact`, `trajectory_in_order`,
  `trajectory_any_order`, `trajectory_precision_recall` (precision and recall reported
  separately — low precision is wasted work, low recall is work undone),
  `trajectory_step_efficiency`, `trajectory_loop_detection`, and `trajectory_recovery`.
  Fully additive and default-off: a target that emits no trajectory behaves exactly as
  before, `SCHEMA_VERSION` is untouched, and `RunResult.to_dict()` omits the `trajectory`
  key when absent so historical result JSON is byte-identical. A scorer with no trajectory
  to grade returns `passed=None` with a comment rather than a failing `0.0`, so a text-only
  suite's aggregate pass rate is not silently dragged to zero; the emitted value is the
  documented `on_missing` knob, since values still enter the mean. ADR 0031 amends
  `docs/CHARTER.md` §4 invariant 1 narrowly to permit this additive core-model extension and
  explicitly does **not** amend the `eval_harness ⇎ flow_corpus` airgap.

  **Hardening pass (same PR).** An objective self-review plus five Copilot review comments
  found nine further issues, every one reproduced by execution. Two defeated the module's
  own stated purpose: `json.dumps(default=str)` embedded **memory addresses** in the
  canonical form, and `set`/`frozenset` arguments fell through to the scalar branch and were
  rendered by `str()` — so the *same* trajectory canonicalised three different ways across
  three `PYTHONHASHSEED` values, yielding three different verdicts. Unknown types now render
  as `type:value` (deterministic, and type-distinguishing, so two classes whose `__str__`
  agree no longer collide) and sets are sorted by canonical representation. The tests for
  this assert **across subprocesses**, because a same-process test passes against the bug.
  `ToolCallRecord.arguments` and `TrajectoryStep.metadata` are now `MappingProxyType`:
  `frozen=True` blocked attribute rebinding but not in-place mutation, so a constructed
  record could silently change its own canonical form. `trajectory_recovery` was O(n²) —
  it re-sliced the step tail per error and scanned it twice — on precisely the looping,
  repeatedly-erroring agent it exists to catch; a single reverse pass over suffix flags
  takes a 5,000-error trajectory from quadratic to 1.6 ms, and it now emits a stable
  metadata key set on both branches instead of different keys on pass and fail. Deeply
  nested and malformed-reference arguments returned `passed=False` (the engine converts a
  scorer exception into a failing verdict); both now return `passed=None`, since unscoreable
  input is not a failing agent. All three new modules gained `logging.getLogger(__name__)`
  with lazy-`%s` debug at the normalisation, failed-match and not-applicable decision points.
  `CallableTarget` now passes a returned `TargetOutput` straight through, so an agent can
  attach a trajectory from a YAML config without a bespoke `TargetRunner` — previously no
  built-in target could emit one at all, making F-051 unreachable from config.

### Changed
- **`openspec-peer-review` skill 1.0.0 → 1.1.0.** The procedure now codifies the two-pass
  protocol the repo's last two major reviews actually used (pinned-SHA mechanical
  fact-check with CONFIRMED/CORRECTED/REFUTED verdicts, then an adversarial design review
  whose refuted attacks are recorded, never deleted), the findings ordering, and a new
  `references/two-pass-protocol.md` with both worked examples
  (`openspec/changes/add-eval-matrix-completeness/review.md`,
  `docs/plans/agent-eval-coverage/REVIEW.md`). Subjective tier unchanged (no `evals/`).

### Fixed
- **Eval-integrity guard reachability (F-052).** The protected-path guard is only as good as
  the set of PRs it runs on, and that set is decided by a *second* list —
  `quality-gates.yml`'s `on.pull_request.paths` — which nothing asserted agreed with
  `scripts/eval_protected_paths.py::PROTECTED_PATTERNS`. They had drifted. Measured with real
  glob semantics, **9 of 15 protected patterns could not trigger the guard at all**:
  `features.schema.json`, `config/**`, all five sibling `*/tests/**` roots, `.github/**`
  beyond `workflows/` and `actions/` (so `CODEOWNERS`, which is what makes the label gate
  meaningful, sat outside it), and `architecture.yaml` — which is protected *precisely*
  because editing its declared component edges could quietly dissolve the
  `eval_harness ⇎ flow_corpus` airgap. The filter is widened to cover all 15, but the fix is
  the validator, not the edit: new `scripts/check_guard_reachability.py` **imports**
  `PROTECTED_PATTERNS` and reuses that module's `_glob_to_regex` — a second copy of either
  would recreate exactly the divergence it exists to prevent — parses the workflow that
  invokes the guard, and fails CI when any pattern has no covering filter. Same rationale as
  F-050 above, one layer down: a gate that cannot fire is protection in name only. Wired into
  `quality-gates.yml` and `check_charter_invariants._EXPECTED_GATE_SCRIPTS`, with
  `--json`/`--verbose` matching the sibling gates. Four of the tests are **mutation** tests
  (delete a filter, assert the check fails) — a guard that silently stops detecting drift is
  worse than none, because the green tick is read as evidence.
- **NaN and infinity silently deleted statistical-power floors
  (`behavioral_regression`, `flow_corpus`).** Every comparison against NaN is False, so a
  non-finite threshold passed *all* of the range guards untouched: `nan <= 0` is False,
  `nan < bound` is False, and `lo <= nan <= hi` is False. Reproduced: with
  `power_min_sample=nan`, `is_directional_only(n=30, …)` returned `False`, so a 30-pair
  sample stopped being directional-only and became **gate-eligible** — turning an honest
  `ESCALATE` into a real ship/no-ship decision on data far below the declared power floor.
  The κ-gate, the reliability report, the confidence cross-check and the detector all route
  through that one call. Infinity is the mirror image: it clears every `> 0` check and
  produces a maximally-wide interval. `math.isfinite` is now checked **inside** the three
  shared validators (`_require_positive` / `_require_at_least` / `_require_in_range`), so
  every field that delegates to them is covered at once rather than by a check repeated at
  each call site; error messages now name the offending value. `flow_corpus.config` used nine
  inline `if` checks instead, so the same four helpers were extracted there first — a net
  *reduction* in duplication, not a second style. The two copies cannot be shared: the
  packages may both depend on `agent_core` but not on each other, and `agent_core` is
  deliberately dependency-free. `flow_corpus`'s previously-unguarded `max_brier_reliability`,
  `min_canary_margin` and `rotation_stability_threshold` gain the finite check only, since
  inventing bounds would reject configs that work today; `wilson_z` additionally gains the
  positivity check every other home for that field already has (`behavioral_regression.config`,
  `agent_core.config`, `eval_harness.config.models`' `gt=0`). Backwards compatible — only
  input that was always invalid is rejected. Both packages' non-finite tests derive their
  field list from the dataclass rather than listing it, so a threshold added later is covered
  automatically; the CLI `--set power_min_sample=nan` path is asserted end to end, since
  `cli._coerce` is the reachable entry point that produces a non-finite float.
- **Retracted a design error in the merged `add-repeat-reliability-metrics` proposal.** That
  package prescribed folding the attempt index into the per-item seed —
  `(base_seed, item_index, attempt_index)` — calling it "the single most important line in the
  change", to stop a deterministic target reporting a "fabricated `pass^k = 1.0`". Verified
  against the tree, it is wrong on both counts. `Target.run(self, item)`
  (`targets/__init__.py:22`) receives **only the item**; `engine.py:152` calls
  `self.target.run(item)`; the per-item RNG goes into `RunContext` (`engine.py:240-241`) and is
  handed to **scorers**, never to the target — so re-seeding cannot change target behaviour at
  all. And `ModelTarget` defaults `temperature=0.0` (`targets/model.py:69`), so for a genuinely
  deterministic target k identical results and `pass^k = 1.0` are the *correct* answer; the agent
  is perfectly reliable under that configuration. Shipped as written, the change would have
  injected variance into the harness and reported it as agent unreliability — inverting the defect
  it was meant to prevent, which is worse than the alleged bug. The requirement is rewritten to
  what actually holds: k genuinely independent `target.run` invocations (no memoisation may
  collapse them — none exists today), **no** harness-injected variance (all variation must
  originate in the target's own sampling), and a diagnostic whenever the configuration makes
  `pass^k` structurally uninformative — *"`pass^k` is 1.0 because sampling is deterministic, not
  because the agent is reliable"* — the same vacuous-pass lesson ADR 0029 records. Corrected in
  the proposal, design, spec, tasks and review, plus the two derived statements in
  `docs/plans/agent-eval-coverage/REVIEW.md` §B14 and `NEXT_STEPS.md`. Root cause, recorded in
  the package's review: the finding was asserted from a plausible reading of `engine.py:41`
  without tracing where the returned RNG is consumed — one `grep` for `target.run` would have
  refuted it.
- **The ledger's provenance check was decorative, and the OpenSpec index had rotted.**
  `validate.py` verifies that every `implemented_in` resolves to a real commit, but CI never
  passed `--strict`, so failures printed as warnings nobody read. Under enforcement, **15 of
  50 refs were bad**: 6 carried the literal placeholder `"local"` (F-045, F-047, F-049, F-050,
  F-051, F-052) and 9 across 8 features (F-006, F-007, F-011…F-016, F-039) pointed at branch
  SHAs lost to squash merges. All 15 are repaired to the commit on `main` that added both the
  feature's ledger entry and its `scripts/validations/F_0NN.py` proof — two independent
  derivations that agree on one commit per feature — and `quality-gates.yml` now runs
  `--strict`. Safe to enforce because `implemented_in` is optional: omitting it is the
  supported way to say "not landed", and only a *present but unresolvable* ref fails.
  `_check_git_refs` additionally downgrades itself to warnings on a **shallow clone**, where
  30 of 50 refs "fail" purely because the commits were never fetched — reporting that as
  provenance rot trains readers to ignore the finding, which is how it got ignored in the
  first place.
  Alongside it, the OpenSpec front-end had drifted the same way: four changes whose capability
  had shipped still read `Status: proposed`, and `openspec/README.md`'s "Current changes"
  index listed **2 of 9**. `add-agent-trajectory-evaluation` (F-051),
  `eval-proxy-and-estimator` (F-047), `merge-gate-health-integrity` (F-049) and
  `skills-ci-coverage-floor` (F-050) move to `openspec/changes/archive/` (first use) stamped
  with their F-ID and landing SHA, with every inbound reference repointed and the relative-link
  depth inside each package corrected. The index now lists all five in-flight changes plus an
  archive table, and a new blocking *OpenSpec change index* guard in `docs.yml` derives both
  lists from the directory tree and fails when an in-flight change is unlisted **or** an
  archived one is still linked as in-flight — either direction alone still lies. ADR 0023 and
  ADR 0031 flip to Accepted (both landed), and 0031 gains its missing `docs/decisions/README.md`
  index row. `docs/openspec-spike.md` records that its own evaluate-and-decide trigger has
  fired with the keep-or-delete ADR outstanding — deliberately not decided here — and what the
  interval actually showed: the layer's failure mode is silent staleness, which is the
  "second, weaker registry" risk that document predicted, now observed and mechanically checked.
- **SessionStart bootstrap missed one package.** `.claude/hooks/session-start.sh` installed the
  root package and four siblings but not `claude-foundation`, so `make check-all` died in that
  target with `No module named 'foundation_tools'` and, before that, `Library stubs not
  installed for "yaml"` — its declared `types-PyYAML` never got installed either. Every package
  the sweep recurses into is now installed, `claude-foundation` with its `[dev]` extra. Also
  fixes a shell short-circuit: `&& [ -n "$PINNED" ] && …` made the whole chain report failure
  when no pin was found, printing the "bootstrap incomplete (offline?)" warning after a
  perfectly successful install.
- **Skills CI coverage floor (F-050, ADR 0030).** `skills-ci.yml`'s `paths:` filter listed 7
  of 8 skills with a dedicated job (`dataset-lint` was omitted), and no workflow at all
  triggered on the 3 skills with no dedicated job. A PR touching only one of those 4 skills
  ran no lint, no mypy, no pytest, no `validate_skill.py`, no marketplace validation, and —
  the sharpest edge — no `check_skill_script_drift.py`, so editing a vendored
  `skills/*/scripts/validate_skill.py` copy (the exact drift that guard exists to catch)
  triggered nothing. The `paths:` filter is now a single `skills/**` glob. A new `all-skills`
  job discovers every `skills/*/` directory dynamically and runs `validate_skill.py --tier
  structural`, `skill_marketplace.py validate`, and `check_skill_script_drift.py` over all of
  them, plus an inline guard asserting every skill is registered in `marketplace.yaml` and
  either has a dedicated job or a documented `EXEMPT` entry — each entry re-checked against
  `evals/evals.json` so a stale exemption fails loudly instead of drifting silently. ADR 0030
  codifies the three exempted skills (`hierarchical-recursive-brainstorm`,
  `openspec-quality-plan`, `openspec-peer-review`) as `docs/SKILL_TEMPLATE.md` §5.B's existing
  "Subjective skills" class — a classification those skills already self-declare in their own
  `SKILL.md`, now enforced at the CI layer. `F_050.py` is wired into
  `tests/test_validation_scripts.py` and `quality-gates.yml`'s coverage step, not merely
  smoke-tested by `scripts/validate.py`. Decision-changing: a skill added without
  registration or CI coverage now fails closed, where it previously passed silently. No
  existing skill's own job, `SCHEMA_VERSION`, or registry alias changes.
- **Merge-gate calibrator-health integrity (F-049, ADR 0029).** The calibrated merge gate's
  fourth health floor could report a pass having measured nothing, and reaching `AUTO_MERGE`
  that way is reproducible under stock `GatePolicyConfig()`: 6600 `HUMAN_AUDIT` records with
  every `raw_confidence` in `{0.05, 0.45}` gave `bin_ci_width=0.0`, `is_trustworthy=True`,
  `tau=1.0`, and auto-merged a change at `raw_confidence=0.45`. `_upper_half_ci_width`
  scanned only bins above raw 0.5 and accumulated into a `0.0` initialiser, so an empty
  region returned the identity of a `max`-reduction and satisfied `max_bin_ci_width`
  vacuously. It was also on the wrong axis — `decide()` gates on the *calibrated* `p`, so
  the raw-score range was never "where auto-merges actually happen", and `tau` cannot define
  the region because `tau` is derived *from* health. `_operating_bin_ci_width` now defines
  eligibility by the per-decision Wilson floor (a bin whose Wilson **upper** bound cannot
  reach `wilson_floor` can never be an operating point, whatever `tau` becomes), returns
  `None` when nothing qualifies, and `is_trustworthy` rejects `None`. On the regression
  fixture the same input moves from `0.0` to `0.7935`.
  `GatePolicyConfig` gains a `__post_init__` bounding all nine tunables — rejecting the
  vacuous endpoint, allowing the maximally-strict one — plus a CLI flag per tunable on
  `merge_gate_ci` with an exit-2 usage path, finally supplying the seam behind ADR 0005 §3's
  standing promise of a *human-set* `risk_target`. `min_auroc` is bounded strictly above 0.5
  so the single-class AUROC sentinel cannot pass the floor it is documented to fail;
  `--protected-auto-merge` is deliberately not exposed. The bin count is single-sourced
  (`calibration.DEFAULT_N_BINS` + `GatePolicyConfig.n_bins`, threaded explicitly), routing is
  unified in `_bin_of` so `fit` no longer sweeps out-of-contract scores into the top bin
  while `bin_index` floors them to bin 0, and `min_calibration_n` now floors the held-out
  fold the other metrics are measured on rather than the both-fold total that overstated it
  2×.
  **Decision-neutral today** — the live store holds 71 records and zero `HUMAN_AUDIT`
  labels, so every domain cold-starts to `ESCALATE` and none of these paths execute.
  **Decision-changing when the gate goes live:** the sample floor counts held-out records,
  an unmeasurable region blocks a domain, and out-of-contract scores move from the top bin to
  bin 0 — all strictly fail-closed. The re-axis is looser in exactly one direction: mediocre
  mid bins that inflate today's width but can never be operating points no longer block a
  domain, which was collateral rejection rather than protection. Operators should note that
  under honest measurement `max_bin_ci_width=0.20` may require ~50+ high-accuracy audits in
  every eligible bin and could keep the gate closed — the correct default per ADR 0005, and
  now a visible constraint rather than one bypassed by a vacuous `0.0`.
  No `SCHEMA_VERSION` bump, no store migration (`bin_ci_width` is computed per run and never
  persisted), auto-merge stays default-off.
  **Peer-review hardening pass (same change):** an objective self-review found the fix above
  had itself regressed `fit`'s and `_operating_bin_ci_width`'s complexity from O(n_bins·n) to
  O(n_bins²·n) — routing per-bin membership through `_bin_of`'s own O(n_bins) scan, once per
  bin, turned one O(n_bins) scan per score into O(n_bins) of them. Measured at ~3.8s for
  `n_bins=200` on 5000 scores, a real hang/timeout risk once the bin count became an
  operator-facing CLI flag. Fixed with a shared `_bucket_by_bin` helper that assigns each
  score to a bin exactly once and groups — verified bit-for-bit identical to the
  pre-regression output across every `n_bins` tested, ~190× faster at `n_bins=200`. Also adds
  `GatePolicyConfig.n_bins`'s upper bound (`MAX_N_BINS=1000`, a resource-safety ceiling, not
  a vacuous-endpoint rejection); a direct unit test for `_policy_from_args`'s CLI-flag-to
  -field mapping (no prior test would have caught a `wilson_floor`/`wilson_z` swap, since
  both fields reject the same invalid probe values for different reasons); a fold-collapse
  test at N=8 rather than only the N=1 case where the sample floor masks the effect; and a
  docstring correction on `_require_finite_in` (its `math.isfinite` guard is load-bearing for
  the two `hi=math.inf` fields, not primarily the NaN-comparison precedent it cited).

### Security
- **Credential scrub + fail-closed secret scanning (F-048).** A Langfuse secret/public key
  pair sat unredacted in three tracked files (`HARNESS_SPEC.md`,
  `docs/decisions/0003-langfuse-integration.md`, `progress.md`) while **no workflow ran any
  secret scanning at all** — a gap opened by the 2026-07-03 Phase 0 plan and never landed.
  The literals are now redacted, and `.gitleaks.toml` plus a `quality-gates.yml` `secret-scan`
  job land the gate with a deliberate asymmetry: the working-tree scan (`--no-git`) is
  fail-closed, while the history scan is report-only, because the keys are already public in
  remote history and a rewrite would invalidate every clone, open-PR base, `implemented_in`
  provenance SHA, and the `merge-gate-data` lineage for no real security gain (ADR 0027).
  **Rotation is not asserted** — an earlier draft of this work claimed the keys were "revoked,
  confirmed before this change merged," which was untrue for another three weeks; the
  confirmation is a human checklist item that blocks the public-facing work.
- **`SECURITY.md` and `README.md` claimed two controls that did not exist.** Both stated
  secret scanning already ran in CI (it did not — this change is what makes it true) and that
  Snyk "monitors dependencies continuously" (no workflow references Snyk; `docs/CHARTER.md` §5
  lists it as future work). Snyk is now described accurately as a documented manual step.

### Fixed
- **Charter-alignment audit findings.** A governance-drift audit (`docs/CHARTER_ALIGNMENT_AUDIT.md`)
  found the charter's `Protocol`-based-DI claim didn't hold for `Judge`/`Scorer`/`Sink` (they
  were `abc.ABC`, and no `Clock` seam existed), `ModelTarget` hardcoded operational defaults
  outside a typed `*Config`, `HARNESS_SPEC.md` described a stale single-package project that
  contradicted the current 5-package charter while `GOVERNANCE.md` still called it canonical,
  the `claude-foundation` staging directory's rationale was undocumented against ADR 0017's
  literal "never vendored" wording, and a roadmap precondition (the agent-confidence artifact)
  was stale. All five fixed: `core/interfaces.py`'s `DatasetSource`/`TargetRunner`/
  `ResultSink`/`Judge` are now `typing.Protocol`; `Scorer` stays `abc.ABC` — a py3.10 CI
  regression (Protocol's `__init__` doesn't reliably propagate to subclasses that don't
  redefine it on 3.10) caught it before merge, and the charter's invariant 3 wording now
  documents that exception rather than overclaiming full Protocol coverage;
  added `agent_core.protocols.Clock`/`SystemClock`/`FixedClock` and wired it through
  `audit_sampler`/`merge_seed`/`outcome_labeller`/`merge_gate_ci`; added `ModelTargetConfig`;
  rescoped `HARNESS_SPEC.md`/`GOVERNANCE.md`; added [ADR 0028](docs/decisions/0028-claude-foundation-staging.md);
  updated the charter's roadmap wording. See the audit report's "Resolution" section for detail.
- **Four committed merge-conflict markers, undetected because nothing checked for them.**
  An orphan `>>>>>>> origin/main` trailer (no matching `<<<<<<<`/`=======` — a clean merge that
  dropped the wrong side) sat in `NEXT_STEPS.md`, `AGENTS.md`, and `CHANGELOG.md` (×2). Removed,
  and `quality-gates.yml`'s `gates` job gained an inline, dependency-free sweep of every
  git-tracked file for all four 2-way/diff3 marker forms (including the bare/orphan trailer
  shape that slipped through here) so this class of defect fails CI going forward instead of
  landing silently.
- **F-048 (credential scrub + gitleaks) was still `status: in_progress` after landing via #83.**
  `features.yaml` now reads `status: done` with `implemented_in` pointing at the merge commit;
  `validate.py --tier fast` (which only runs `done`-status validators) now actually enforces
  `F_048.py` in CI, closing a gap where the gate existed but wasn't wired into the ledger.
- **Hardened matrix eval tools test suite.** Refactored `tests/test_matrix_eval_tools.py` to completely eliminate hard-coded return values and fragile `try...except pass` swallows in the evaluation plugin tests (Judges, Datasets, Scorers, Sinks). Replaced them with robust, dependency-injected mocks leveraging `patch.dict('sys.modules')` for true offline regression coverage regardless of local environment state.
- **`.gitignore`'s blanket `*.html` silently dropped deliverables.** Committed sample reports
  and HTML golden fixtures under `docs/samples/`, `tests/fixtures/`, and
  `agent-core/tests/fixtures/` are now tracked; previously they would have passed locally and
  failed in CI on a missing file.

### Security
- **Argument injection in the `merge-gate verdict` workflow dispatch.** The optional
  `selection_propensity` input was interpolated into an *unquoted* shell scalar and then
  word-split into the `python` invocation, so an input of `0.5 --store /tmp/x` appended a
  second `--store` that argparse resolves last-wins — redirecting where the verdict was
  written. Routing the value through `env` (already done) stops *template* injection; only
  a quoted bash-array expansion stops *argument* injection. Reachable by an authorized
  auditor only, since the job gates on `MERGE_GATE_AUDITORS`. Pinned by `F_047.py`, which
  now fails if the array expansion is ever replaced by a bare `$PROP_ARGS`, and by a test
  asserting the value reaches argparse as a single token.

### Added
- **`scripts/check_charter_invariants.py`, a mechanical charter-conformance gate.**
  `scripts/check_charter_drift.py` only checks that the charter's markdown links resolve;
  this new gate re-checks a battery of the charter's actual *claims* — package existence,
  agent-core's zero-runtime-dependency claim, `SCHEMA_VERSION` single-sourcing, per-package
  coverage-floor declarations, the eval-integrity approval-label string, the named quality
  gates staying wired into CI, the Protocol-based interfaces, and the auto-fix/auto-merge
  default-off flags — plus a non-blocking heuristic warning for likely magic-number
  defaults. Wired into `quality-gates.yml` alongside the drift guard. Added after
  `docs/CHARTER_ALIGNMENT_AUDIT.md` found drift the link-only guard could not have caught.
- **Merge-gate soak-stats (F-040)**: `agent_core.store_sync.soak_progress(records, target)` — a
  pure, read-only summary (total/pending/labeled, HUMAN_AUDIT count, per-domain cold-start keyed on
  `AuditConfig.per_domain_floor`, n-vs-target, merge velocity/day, days-to-target) — plus an opt-in
  `store_sync stats --soak-target N` that adds a reserved `_soak` block. Default `stats` output is
  byte-identical; no store mutation (property-tested), no TCB change, no schema bump. Soak
  enablement stays time-gated (ADR 0005); this only makes progress observable.
- **Reasoning & Planning Skills (`hierarchical-recursive-brainstorm`, `openspec-quality-plan`, `openspec-peer-review`):** added three composable reasoning skills to the marketplace for performing controlled hierarchical research, generating production-grade OpenSpec packages, and objectively peer-reviewing them. Validated purely structurally with no evaluation-defining paths modified. Configurable via documented defaults.
- **A single-sourced propensity contract.** `is_valid_propensity` / `format_propensity`
  replace three independent restatements of `0.0 < p <= 1.0`, which had already drifted
  (only one also checked `math.isfinite`) and were equivalent only because `0.0 < nan` is
  incidentally `False`. `audit_issue_sync` now also validates at *ingestion*: `float()`
  accepts `"nan"`, `"inf"` and any magnitude, so parsing was never validation — an
  out-of-contract column used to render into the issue body and into a dispatch command
  guaranteed to fail downstream. It is now logged and treated as unknown, so the change
  still gets audited, it just cannot be reweighted.
- **Follow-up hardening + end-to-end propensity wiring (F-047, ADR 0026).** Closes the
  review findings on the merged proxy/PPI++ work and makes `selection_propensity` live.
  Correctness: `proxy_eval` no longer reports a by-construction `AUROC = 0.5` for a
  constant proxy (its sibling `calibration_report` had always withheld it); a tuned
  `lambda` can no longer run out of residual degrees of freedom (`min_labeled >= 3` plus a
  runtime guard — at `n = 2` the residual variance collapsed to `0.0` and the interval
  reported a half-width of **0.06 from two observations**); the proxy-range check streams
  instead of materialising two full copies of the unlabeled pool; and a stale docstring
  pointed at the pre-split module. **Propensity is no longer dead data**: `merge-gate-audit`
  selects `--with-propensity`, `audit_issue_sync` carries the value into the audit issue
  *and* the dispatch command the human copies out, and `merge-gate-verdict` →
  `record_audit_verdict` thread it to the write boundary — backwards compatible at every
  seam (both `selected.txt` formats parse, bare ids still accepted, a blank input records
  NULL rather than a fabricated probability). Also corrected: the spike's removal
  instructions omitted the `mkdocs.yml` nav entry, which leaves a dangling-nav warning
  (measured — the build is non-strict by design, so it is a warning today and a hard
  failure under `--strict`). Docs refreshed to match: C4 merge-gate component diagram,
  `NEXT_STEPS.md` (whose `N≥20` claim contradicted the peer review merged alongside it),
  both READMEs, `AGENTS.md`, the e2e runbook, and the ADR index.
- **Peer-review hardening of the proxy/PPI work (`agent-core`).** An adversarial
  correctness review and a gap/hygiene audit of the change below found six real defects,
  all fixed here: a prediction-powered interval could render **inverted** (`lo > hi`, a
  negative half-width, the point outside its own interval) with no degeneracy flag;
  `variance_reduction` was computed from `[0,1]`-clipped bounds and **over-reported a 3%
  gain as 94%**, non-monotonically; per-bin slices assumed a unit-interval proxy and
  silently dropped every out-of-range external judge score; `build_dataset` took the
  *first* audit row rather than the authoritative one, disagreeing with
  `OutcomeStore.resolved()`; small-n coverage sat below nominal because the fitted
  `lambda` was not charged a degree of freedom; and three files had grown past the repo's
  500-line budget (`scripts/check_size_budget.py`), which the `quality-gates.yml` path
  filter would have left latent for an unrelated PR to inherit. `calibration.py` is
  therefore split into `ppi.py`, and the report into `report_types.py` +
  `calibration_report_render.py`, with every previously importable name still resolving
  from its original module (`calibration_report.__all__` pins that). The report also now
  renders the classical (λ=0) baseline the reduction is measured against, and states that
  cross-domain aggregates are **unweighted** while no estimator applies the `1/p`
  correction the per-domain audit floor calls for. Full workspace gate green: harness
  97.55%, agent-core 98.45%, behavioral-regression 100%, flow-corpus 100%,
  flow-protocol 100%, scripts 95.85%, foundation 96.03%; 43/43 feature validations pass.
- **Proxy-correlation measurement, audit-selection propensity, and a dual `wilson`/`ppi++`
  report estimator (`agent-core`).** Implements the minimal, reversible slice from the
  2026-07-25 peer review. **The merge gate is untouched** — `merge_gate.decide()`, `tau`,
  `wilson_floor`, `risk_target`, and `min_calibration_n` are unchanged, and auto-merge
  remains off; every addition is report-side or additive data.
  - **`agent_core.proxy_eval` (new).** Read-only CLI + library measuring how well a cheap
    proxy predicts the authoritative `HUMAN_AUDIT` label, reported **marginally and
    conditionally** on the subsets the gate operates over (`score >= tau`, per-bin), with
    the implied effective-sample multiplier `1/(1-rho^2)`. Proxies are pluggable via a
    `ProxyExtractor` Protocol — `RawConfidenceProxy`, `PassiveLabelProxy`, and
    `MappingProxy` (the seam for externally-computed scores such as an LLM judge, keeping
    `agent_core` dependency-free). Degenerate slices are named, never scored: a constant
    proxy, a single outcome class, fewer than three pairs, or a perfect correlation (any
    two points are collinear, so `n=2` yields `|rho|=1` and a nonsense multiplier).
  - **`ppi_plus_interval` + `pearson_r` + `effective_n_multiplier` (`agent_core.calibration`).**
    Power-tuned prediction-powered interval for a mean outcome rate; `lambda` is
    variance-minimising and clamped, so `lambda = 0` recovers the classical estimator and
    the tuned form is asymptotically never worse. **Fail-closed:** where the normal
    approximation cannot be trusted — too few labels, a single outcome class (zero
    variance would collapse the interval to a false-certainty point), a constant proxy, or
    no unlabeled pool — it returns the **Wilson** interval and says why. Carries a
    same-family `lambda = 0` baseline so a reported gain is attributable to the proxy
    rather than to the interval type.
  - **`OutcomeRecord.selection_propensity` + `audit_sampler.select_for_audit_detailed`.**
    The sampler now reports each pick's marginal inclusion probability and `record_verdict`
    stores it, enabling later Horvitz–Thompson / prediction-powered reweighting (which
    cannot be reconstructed after the round). Nullable and additive: pre-existing rows load
    with `None`, `select_for_audit` keeps its exact signature and selection (same RNG
    order), and the CLI's default output is byte-identical (`--with-propensity` is opt-in).
  - **`calibration_report --estimator {wilson,ppi++}`.** Dual-reports both intervals plus
    the variance reduction; `wilson` remains the default and the only estimator the gate
    uses.
  - Hardening found by the property suite: `pearson_r` no longer raises `ZeroDivisionError`
    when two tiny-but-positive variances underflow to zero in their product (roots are
    taken before multiplying), the moment helpers report an unrepresentable spread as `inf`
    instead of raising `OverflowError`, and `inclusion_probability` is written so
    `p >= base_rate` and `p <= 1` hold exactly in floating point.
- **Peer review of the "swap Wilson → PPI++" estimator critique + OpenSpec coordination spike
  (planning only).** Added a committed objective peer review
  (`openspec/changes/archive/eval-proxy-and-estimator/review.md`) that verifies the critique's
  arithmetic and citations but corrects it on target, magnitude, and mechanism: the merge
  gate's real activation bar is a four-gate Wilson stack needing ~380 near-perfect audits per
  domain (not one `N≥20` gate), and PPI++ on the calibrated-confidence proxy buys only
  ~1.05–1.1× effective-N at the `min_auroc=0.65` floor — the leverage is in the *proxy* choice
  (passive REVERT/CI labels or an independent LLM judge with conditional variance), not the
  estimator swap. Introduced a reversible **OpenSpec** front-end (`openspec/`, `docs/openspec-spike.md`)
  used as a thin coordination layer over the existing enforced spec system (`features.yaml` +
  `scripts/validations/F_*.py` + ADRs), with a change proposal (proposal/design/tasks/spec
  deltas) for proxy-correlation measurement, audit-selection-propensity logging, and a dual
  `wilson`/`ppi++` report estimator. Planning/documentation-only — no evaluation logic, gate
  threshold, `agent_core` source, or `features.yaml` change; the merge gate is untouched.
- **Enterprise documentation, licensing & repository organization.** Added an Apache-2.0
  `LICENSE` (+ `NOTICE` and per-package copies) and declared PEP 639 packaging metadata
  (`license`/`license-files`/`readme`/`classifiers`/`[project.urls]`, setuptools `>=77`) across
  every package; added the root community-health set (`CONTRIBUTING`, `SECURITY`,
  `CODE_OF_CONDUCT`, `SUPPORT`, `GOVERNANCE`, `MAINTAINERS`); authored the missing component
  READMEs (`flow-corpus`, `flow-protocol`, `skills`, `scripts`, `experiments`, `src/eval_harness`)
  and `behavioral-regression/CHANGELOG.md`; added a `docs/` index, an ADR index, and a
  `docs/STYLE.md` taxonomy; introduced a `mkdocs-material` site (`mkdocs.yml`, `.[docs]` extra);
  and restructured the root README (badges, TOC, monorepo map). Documentation- and
  metadata-only — no evaluation logic, gate threshold, or `features.yaml` change.
- **Agent-record calibration: routing, proxy confidence & report (F-042/F-043/F-044, ADR 0023).**
  Closes the agent-record calibration gap — the merge-gate outcome store had crossed its soak
  target but every record was `agent_version:null` / `domain:human/*` / `raw_confidence:0.0`,
  i.e. zero agent-authored signal, so the agent-domain predictor was degenerate by construction.
  - **F-042 — seed routing + confidence proxy.** The seed-on-merge workflow now classifies each
    merged change by its PR **head-ref prefix** (matched against `config/agent-authors.yaml`, e.g.
    `claude/*`) rather than author login (uniform across this repo). An agent change is seeded in
    the un-prefixed agent domain with the real `agent_version` and a **deterministic proxy
    confidence** (`scripts/agent_confidence.py`) — a pure function of diff size, file count,
    test-to-code ratio, and protected-path touches, mapped through a clamped sigmoid, no network
    or model call. Human, PR-less, or any unclassifiable change keeps the reserved
    `human/<domain>` namespace at confidence `0.0` (fail-safe: anything not positively classified
    as an agent stays out of the agent pool, per REVIEW.md §6). This makes the agent-domain
    calibration corpus non-degenerate for the first time.
  - **F-043 — calibration report.** `agent_core.calibration_report`, a read-only CLI reporting
    ECE / Brier (+ Murphy decomposition) / AUROC / selective-risk abstention with Wilson CIs over
    the agent-domain slice, reusing the existing `agent_core.calibration` primitives (no new math).
    The authoritative `HUMAN_AUDIT` view (the only one that may feed the auto-merge τ) is kept
    separate from passive diagnostics, and a constant/single-class predictor is reported honestly
    as `DEGENERATE` instead of the by-construction `0.5`. Emitted to the daily outcome-labeller run
    summary (read-only, after the store push).
  - **F-044 — one-off reversible backfill.** `scripts/migrations/agent_domain_backfill.py`
    re-attributes historical agent SHAs from `human/*` to the agent domain with the same computed
    proxy confidence, gated on an explicit committed `SHA→agent_version` list, writing a per-store
    `*.pre-backfill.bak` safety copy so the migration is reversible.

### Hardening
- **Agent-seeding hardening & reuse (F-046, follow-up to F-042…F-044).** A review-driven pass
  (self-audit + Copilot + CodeRabbit) resolving tech debt in the above without changing the trust
  boundary:
  - **Fail-safe seed routing** — a non-zero exit from the classifier now writes a human-lane
    fallback `agent.json` and logs it to the run summary instead of aborting the whole seed job
    under `set -e` (ADR 0023 §2); an undeterminable file set raises rather than scoring all-zero.
  - **No hardcoded values** — the reserved namespace is single-sourced in
    `agent_core.domains.HUMAN_NAMESPACE` (validated to equal `config/merge-gate-domains.yaml`),
    and the report's `n_bins` / `risk_target` / `z` come from a validated `ReportConfig` dataclass.
  - **Reuse / DRY** — new `scripts/_config.py` owns the shared changed-file / strict YAML-loader
    idioms (previously duplicated across `agent_confidence.py` and `merge_gate_context.py`); the
    backfill routes git through the sanctioned `agent_core.subprocess_util.run_failsafe`.
  - **Robustness** — `read_nul_delimited` reads bytes + `surrogateescape` (non-UTF-8 `git -z`
    output no longer crashes), the sigmoid clamps its exponent (no `OverflowError` on extreme
    config), and the migration's SHA-list parse is strict (a bare SHA is rejected, not silently
    defaulted).
  - **Security / CI** — `github.actor` is routed through `env:` in both push steps (zizmor
    template-injection), the calibration-report step is `continue-on-error`, and the migration is
    no longer excluded from the scripts coverage gate.
  - **Review-driven refinements** (independent 4-lens peer review + Copilot/CodeRabbit): the
    reserved namespace is now single-authority — `merge_gate_context` validates the YAML
    `human_namespace` equals the canonical `agent_core.domains.HUMAN_NAMESPACE` at load (fail-loud,
    not just the static F-046 check); `ReportConfig` rejects non-finite `risk_target`/`z` and its
    errors name the offending value; the migration gained a start/apply audit log and clean exit-2
    error handling; the labeller's report step leaves a step-summary breadcrumb on failure; the
    backfill reuses `agent_confidence.DEFAULT_PROXY_PATH`; and F-046 pins the seed fail-safe's
    fallback JSON against the classifier's real output shape. New tests cover the binary-file diff
    path, the missing-change_id warning, non-finite config, and the config-flag threading; an e2e
    journey exercises the agent-confidence seed path. All coverage floors hold with margin.
  Ledgered as **F-046**; `scripts/validations/F_046.py` pins the durable invariants.

### Fixed
- **Outcome-record forward compatibility: a newer writer's record crashed every reader
  (ADR 0025).** `agent_core.store_sync` deliberately preserves a line it cannot parse so a
  rolling upgrade never loses data; `agent_core.jsonl` is deliberately strict so a corrupt
  line cannot pass unnoticed. Both are right, but `OutcomeRecord(**json.loads(line))` could
  not tell an **unknown extra key** from a **missing required key** — both raise `TypeError` —
  so the mechanism built to survive a rolling upgrade produced exactly the record that broke
  every other consumer: `merge_gate_ci` exits 1 in both the gate and shadow jobs, failing
  every PR, and `outcome_labeller` / `audit_sampler` / `merge_seed` have no handler at all.
  `OutcomeRecord.from_json` now separates additive schema evolution from corruption — unknown
  fields are dropped and logged by name; malformed JSON, a non-object payload, a missing
  required field, and wrong types all still raise. `store_sync` is untouched and still
  round-trips such a line verbatim, so the writer never rewrites a field it does not
  understand while the reader no longer crashes on one. A test now crosses that seam in one
  assertion, which neither module's suite previously did.
- **Merge-gate fail-open on out-of-contract confidences, and a vacuous ship-gate pass.**
  Found while peer-reviewing the agent-record calibration plan
  (`docs/plans/agent-record-decontamination/`); each defect was reproduced before being fixed,
  and the full sweep — three fixed, ten still open — is recorded in
  `docs/gap-analysis-merge-gate-2026-07-24.md`.
  - **Confidences outside `[0, 1]` could reach AUTO_MERGE.** `NaN` compares False against
    every bin edge and `inf` exceeds them all, so both fell through
    `BinningCalibrator.bin_index`'s scan to its `score >= top edge` return — the
    *highest*-confidence bucket — as did any value above 1.0. Values below 0 escalated, so the
    failure was one-sided toward unsafe: with a trustworthy calibrator, `decide()` returned
    `AUTO_MERGE` for both `NaN` and `5.0`. Latent only because every domain is still
    cold-start (zero `HUMAN_AUDIT` records ⇒ `tau is None`), so it would have activated exactly
    when the gate went live. `ChangeContext` now enforces the `[0, 1]` contract its field
    comment always claimed, and `bin_index` floors any non-finite or out-of-range score to
    bin 0 for records arriving straight from the store, where `OutcomeRecord` applies no
    validation. Exactly `1.0` stays in contract and still lands in the top bin.
  - **`merge_gate_ci` reported bad input as an internal fault.** Invalid values, malformed
    JSON, a missing context field, and a `null` where a value belongs now all exit **2**
    (usage) rather than 1 — and never 0, which CI reads as proceed-to-merge. An unreadable
    `--context` path stays exit 1: the environment failing, not the caller passing a bad value.
  - **`evaluate_calibration` passed slices that cannot evidence discrimination.** An undefined
    AUROC satisfied the resolution criterion vacuously, so a forecaster wrong 100% of the time
    — perfectly calibrated against its own base rate — passed the ship gate, as did a single
    record. Degeneracy is now always reported on `CalibrationReport.degenerate` and logged;
    *enforcement* is opt-in via `CalibrationConfig.min_eval_samples` /
    `require_discrimination`, both defaulting to the prior behaviour, so no existing caller's
    verdict changes and configs persisted before the fields existed still load and round-trip.
    An all-correct golden set is a legitimate shape, so it keeps passing until a caller opts in.
  - **`build_domain_models` decided per-domain autonomy silently.** The `HUMAN_AUDIT`-only
    filter dropped every other record with no count and no log, making an all-passive store
    indistinguishable from an empty one — which is the live state today (43 records,
    12 labelled, 0 audited). It now reports exclusions by reason and warns when no audit
    records exist at all.
- **`claude-foundation/tests/` protected-path gap (F-041):** an independent audit of the
  merged F-039 work found that `claude-foundation/` — structurally identical to the four
  packages F-039 protects — was missed by that sweep. Its `tests/test_eval_gate.py`
  directly exercises an eval-integrity gate (`foundation_tools.eval_gate`) and was
  modifiable in an unrelated PR with no `eval-change-approved` label or CODEOWNERS review
  required. `claude-foundation/tests/**` is now in `PROTECTED_PATTERNS` and
  `.github/CODEOWNERS`.

### Added
- **Skill Validation Assertion Registries & dataset-lint (F-045)**: Refactored `validate_skill.py` to use a dynamic registry pattern (`ASSERTION_GRADERS`) for grading structural assertions without monolithic conditionals (detailed in [ADR 0024](docs/decisions/0024-assertion-graders-registry.md)). Added the `dataset-lint` skill capable of deep-validating generic datasets against customizable rulesets via its own `FORMAT_PARSERS` registry pattern. Introduced full test matrices backing these registries with 100% test coverage.
- **Plugin-registry surface guard:** `tests/test_plugin_registry_surface.py` freezes the
  `eval_harness` plugin registry's config-selectable keys — the `dataset`/`judge`/
  `scorer`/`sink`/`target` registries' primary names *and* their backwards-compat
  aliases (`csv_file` → `csv`, `claude` → `anthropic`, …) — against a committed
  `plugin_registry_baseline.json`, with exact equality: a dropped/renamed key fails CI as a
  breaking change, a new key must be explicitly frozen. This is the compat surface the
  `__all__` guard cannot see, since users select components by string in config rather than
  importing them. The built-in surface is read in a fresh subprocess (the registries are
  process-global and some tests register doubles into them, so an in-process read would be
  order-dependent), keyed by each `Registry`'s own stable `.kind` field rather than its
  Python variable name (immune to a purely internal rename). `--update` refuses to silently
  rewrite the baseline if doing so would drop a key — `--allow-drops` is the explicit,
  reviewed override for a deliberate breaking change.
- **Public-surface backwards-compat guard (F-039):** `tests/test_public_surface.py` freezes
  every package's public `__all__` exports (exact-equality against a committed
  `public_surface_baseline.json`), so a removed or renamed export now fails CI instead of
  silently breaking every config/import that used it — the exact gap that let a breaking
  change land undetected before. Exact-equality by design: a drop or rename fails loudly as
  a breaking change, and an addition must be explicitly frozen too (a reviewable diff) — CI
  fails either way until the baseline is updated to match. Duplicated byte-identically into
  `agent-core/`, `behavioral-regression/`, `flow-corpus/`, and `flow-protocol/`'s own
  `tests/` dirs (each package runs its own isolated suite, so the guard must be
  self-contained there) and drift-guarded against the root canonical via
  `check_skill_script_drift.py`'s `TRACKED_DUPLICATES`. Ledgered as **F-039**;
  `scripts/validations/F_039.py` guards the wiring itself.

### Fixed
- **Sibling packages' `tests/` directories had no protected-path coverage.**
  `scripts/eval_protected_paths.py`'s `"tests/**"` pattern compiles to `^tests/.*$`, which
  only anchors the root suite — `agent-core/tests/`, `behavioral-regression/tests/`,
  `flow-corpus/tests/`, and `flow-protocol/tests/` (every test in those four packages, not
  just their public-surface-guard copies) had no `eval-change-approved` label requirement
  and no `.github/CODEOWNERS` review gate. `PROTECTED_PATTERNS` and `CODEOWNERS` now include
  explicit entries for all four; locked in by new parametrized cases in
  `tests/test_protected_paths.py` and asserted by F-039's validator.

- **Eval-backend validation experiment (`experiments/backend-validation/`):** an isolated,
  self-contained subtree implementing `eval-backend-validation_v1` — decision-grade empirical
  evidence for the eval-backend displacement decision by validating the claimed capabilities
  of Langfuse and Opik against *running* deployments. Probes emit raw observables; a
  **human-signed rubric** (`RUBRIC.md`) maps observables to marks; agents implement and
  execute but never author acceptance criteria, break ties, or recommend a platform (the
  final report has no recommendation section, enforced by a test). Three probe layers: **L1**
  capability (each tool's own SDK/API, harness-independent — an AST test enforces that only
  the L2 modules import `eval_harness`), **L2** integration through the harness's
  vendor-neutral `ResultSink`/`RunResult` seam (an experiment-local `OpikSink` adapter is
  itself the adapter-delta metric; below-sink scope is reported BLOCKED, never improvised),
  and **L3** air-gap (egress-blocked re-run, dual-scored as-shipped vs documented telemetry
  opt-out). Six phases (`preflight`/`deploy`/`l1`/`l2`/`airgap`/`report`) with a strict
  fail-safe discipline: any missing precondition, sign-off, credential, or unhealthy stack
  produces a BLOCKED report naming what a human must do; an unexpected negative-control pass
  HALTs the run. Digest-pinned compose stacks (refused unless pinned), ops-burden metrics
  (setup wall-clock, retries, idle RAM/CPU, image sizes), and reproducibility provenance.
  Consumes the repo core as a dependency only — zero writes outside the subtree, enforced by
  a settings validator, a compose bind-mount check, and a PR-scoped git-diff allowlist.
  Ships **unsigned** (all probes gated behind human sign-off) with its own generated
  quality-gate (196 tests, ≥95% branch coverage, mypy `--strict`).

### Changed
- **Dynamic drift guard script tech-debt resolution:** resolved tech debt in the dynamic drift guard scripts to improve maintainability and performance.
- **CI gate delegation — packages 2-4 of 5 (ADR 0021):** `agent-core-ci.yml`,
  `flow-corpus-ci.yml` (both its `flow-protocol` and `flow-corpus` jobs), and
  `behavioral-regression-ci.yml`'s `behavioral-regression` job now delegate to
  `.github/actions/run-quality-gate` (`check: make check`) instead of duplicating
  ruff/format/mypy/pytest inline — continuing the fan-out `eval-harness-ci.yml` started
  (below) and unblocked by the `F_037` fix (also below): its new `_common.ci_enforces()`
  accepts either inline or delegated wiring, so this rewire no longer breaks the validator
  the way the first one did. Incidentally fixes a real drift bug while delegating: the
  `flow-corpus` and `behavioral-regression` jobs installed an **unpinned**
  `pip install ruff mypy` instead of their own package's pinned `[dev]` extra
  (`ruff==0.15.20`, `mypy==2.1.0` — the same pin the rest of the fleet uses), which
  delegation naturally closes since the package's own `[dev]` extra is what the new install
  command pulls in. `claude-foundation-ci.yml` is deliberately left inline (a separate PR
  deletes it entirely as part of the claude-foundation extraction). Verified locally:
  `make -C <pkg> check` run end-to-end for all 4 packages, matching the coverage numbers
  their own CI reports (agent-core 98.67%, flow-protocol/flow-corpus/behavioral-regression
  100%, all ≥ their 95% floors).

- **CI gate delegation — phase-2 POC (ADR 0021):** `eval-harness-ci.yml` no longer duplicates the
  ruff/format/mypy/pytest steps inline — it delegates to the generated root gate through a new reusable
  composite action `.github/actions/run-quality-gate` (sets up Python, installs the package, runs
  `make check` → `./scripts/quality-gate.sh all`). CI now runs the byte-for-byte same checks as local
  `make check`, per ADR 0020's "local == CI by construction" law. This is the first, pattern-setting
  workflow of ADR 0021's phased rollout; the other five (`agent-core`, `flow-corpus`,
  `behavioral-regression`, `claude-foundation`, `skills-ci`) follow in separate label-gated PRs, and
  ADR 0021 stays **Proposed** until the rollout completes. Consequences surfaced for review: the root
  gate's `ruff check .` spans the whole repo, so this job now also lints the sibling packages (verified
  green); the py3.12 browsable `htmlcov/` artifact is dropped — the shared gate does not produce it (the
  scripts-coverage pass overwrites `.coverage`) and it is a CI-only convenience, not a gate.

### Fixed
- **`main` was silently red on F-031 and F-037; validators decoupled from CI wiring.** PR #64
  (ADR 0021 delegation POC) replaced `eval-harness-ci.yml`'s inline ruff/mypy/pytest steps with a
  call to the generated root gate. Two validators asserted those exact command strings still
  appeared in the workflow, so five assertions began failing the moment the delegation landed —
  `F_031` (lints/format-checks/type-checks `scripts/`, runs the operational-scripts coverage gate)
  and `F_037` (`eval-harness-ci.yml` type-checks `tests`). The failure went **undetected** because
  `quality-gates.yml` — the only workflow that runs `validate.py` — is path-filtered and does not
  fire on `.github/`-only PRs, so the guard ran neither on #64 nor on the merge to `main`.
  Both validators now assert the *guarantee* (the step runs in that suite's CI) rather than one
  wiring of it, via a new shared `_common.ci_enforces(workflow, gate, inline=…, in_gate=…)` helper
  that accepts the inline spelling **or** the delegated form (workflow reaches the gate **and** the
  gate runs the step) and still fails when neither holds. Because the delegated gate lints the whole
  tree instead of naming `scripts`, F-031 additionally guards the one way delegation could weaken
  it — a root ruff `exclude`. `F_031`/`F_037` are now also asserted by
  `tests/test_validation_scripts.py`, which puts them in the **offline pytest suite** that
  eval-harness CI *does* run on workflow edits — so this class of regression now fails at a second,
  unfiltered layer. F-037's skills-ci checks stay inline-matched deliberately: no skill has a
  generated gate yet, so there is no delegated form to assert against.
- **Bot-review round (CodeRabbit):** workspace detection now skips a member directory named
  `all` (reported via `WorkspaceFacts.skipped`, never emitted broken) — its `check-all`/
  `install-all`/`clean-all` targets would collide with the generated aggregates, and GNU
  Make's last-recipe-wins rule would silently drop the member's own delegation. The
  quality-gate SKILL.md now documents that `--lint-path` without a detected ruff
  configuration is ignored with a warning (parity with `--typecheck-path`), a hand-extension
  test writes its sentinel path in POSIX form so it stays valid inside the generated bash
  gate on Windows, and the real-`make` workspace test carries the `slow` marker.
- **Generator review round (8-angle code review; 10 findings fixed):** the `# regenerate:`
  provenance now embeds the generator path AS INVOKED (`sys.argv[0]`, cwd-relative like
  `--root`) — the previous hardcoded `scripts/gen_gate.py` made every committed artifact's
  header unrunnable; the root Makefile (and each member Makefile) gained the same provenance
  line, and a flag-less regeneration over a fan-out Makefile now warns before dropping
  `check-all`. `gen_gate.py --check` verifies the tail's `main "$@"` dispatch invariant (a
  gate truncated at the marker used to pass `--check` while executing nothing), and
  rewriting a pre-marker 1.0.x artifact warns loudly instead of silently discarding hand
  edits. `install-all` delegates to each member's own `install` target so detected install
  commands (dev extras, poetry) are honoured; an empty `check-all` aggregate is omitted
  rather than fabricating a passing no-op; `--lint-path` without detected ruff now warns and
  stays out of provenance (parity with `--typecheck-path`); multi-path gates emit a stderr
  notice when an exported `TYPECHECK_PATHS`/`COVERAGE_SOURCE` override is ignored. The root
  gate lints the WHOLE tree again (`demo/`+`examples/` had silently left the gate; both
  reformatted). Internals: the env-form predicates are single-sourced (a divergence would
  have emitted scripts referencing undefined variables under `set -u`), `_quoted` is reused
  for `--cov` flags, all three GateFacts tuple fields share the empty→`"."` rule, and
  `lint_paths` is appended at the end of the dataclass preserving 1.0.x positional
  construction. Deferred with rationale (NEXT_STEPS): single-instrumented-run coverage for
  the root gate's two suite passes; individually dispatchable named hand-steps.
- **E2E runner Windows cross-platform hardening (21/21 green):** the
  `e2e:backend-validation` step's `--junitxml` flag used string concatenation
  (`'--junitxml=' + $bvXml`) inside a PowerShell `@()` array literal, which
  silently split into two array elements — pytest received the XML path as a
  test directory and collected zero tests.  Fixed to use string interpolation
  (`"--junitxml=$bvXml"`) matching all other suites.  The step's PYTHONPATH
  now also saves/restores around the block so `--cov=backend_validation` can
  locate the package when the editable install is stale.  F-038 validation
  gate prepends `src/` to `sys.path` (standalone scripts don't inherit the
  conftest shim).  Three skill test files gained platform-aware skip guards:
  `_bash_works()` (WSL bash accepts `shutil.which` but cannot execute scripts
  at Windows temp paths — exit 127) and `_can_symlink()` (non-elevated
  Windows users lack `SeCreateSymbolicLinkPrivilege`).

### Added
- **Workspace-wide deterministic gates (P1+P2 of the determinism phase; quality-gate &
  project-setup skills → 1.1.0):** the generators gained monorepo support and the repo now
  dogfoods it end to end. `gen_gate.py` accepts repeatable `--lint-path`/`--typecheck-path`
  flags (multiple mypy paths render one invocation each — per-path runs avoid module-name
  collisions; pyright keeps a single invocation), keeps ALL `[tool.coverage.run] source`
  entries as repeated `--cov=` flags (taking `source[0]` silently measured a subset), embeds
  a shell-quoted `# regenerate:` provenance comment (omitted entirely if an arg carries a
  control character — a newline inside a quoted arg would escape the comment into executable
  text), and owns only the content above a **hand-extension marker**: below it survives
  regeneration, is ignored by the advisory `--check` (prefix-compare), and a `do_extra()`
  defined there runs automatically in `all`. `gen_makefile.py --workspace` detects members
  (immediate-child `pyproject.toml`, sorted, symlinks and unsafe names excluded), emits
  explicit `check-<member>` fan-out targets (`$(MAKE) -C`, only for members whose own
  Makefile has a `check` target — never fabricated), `check-all`/`install-all`/`clean-all`
  aggregates, and one plain Makefile per member. Dogfooded artifacts: root + 5 member
  `scripts/quality-gate.sh` (floors 96/95/95/95/95/85; root carries the F-031 scripts gate
  below its marker, claude-foundation carries `foundation_tools.validate`/`scan`) and root +
  5 member Makefiles — all byte-stable across regeneration and all executed green locally
  (`make check-all`). ruff/mypy dev-extra pins unified (`ruff==0.15.20`, `mypy==2.1.0`) in
  agent-core, flow-protocol, flow-corpus and behavioral-regression, which previously
  floated. `GateFacts` keeps 1.0.x compatibility (string fields coerce to tuples; new
  fields appended, not inserted). AGENTS.md/README gate commands now point at the script
  instead of restating the chain. CI rewiring is deliberately deferred to ADR 0021's
  labeled batch.
- **Determinism phase P3+P4 — ADR 0022 and C4 semantics ownership:** ADR 0022 records the
  determinism boundary for inference skills (consume-don't-contain; the two `--check`
  conventions — fully-derived artifacts gate, hand-extensible scaffolds advise; the
  c4-docs delegation seam; considered-and-deferred: hook wiring → post-extraction M7,
  manifest-derived L2). The `plan`/`test-first`/`code-review` foundation skills now
  consume a committed quality-gate script when the target project has one (generic
  wording, fallback preserved; code-review's no-Bash fork isolation untouched), each with
  a new eval case. `docs/c4_architecture.md` gained a provenance preamble declaring its
  edges **runtime/call semantics** vs the generated **import-edge view**
  (`architecture.yaml` → `architecture.mmd`), the missing `behavioral_regression` (+
  `agent_core`/`flow_corpus`) sibling containers with verified runtime edges, and a split
  of the conflated Plugin Registry box into `core` (Registry[T]) vs `plugins`
  (entry-point discovery); the unreferenced `docs/c4_architecture.svg` was deleted, and
  README/AGENTS architecture pointers now name which artifact owns which semantics.
- **Deterministic generator skills — `project-setup`, `quality-gate`, `deploy` (ADR 0020):**
  three skills that emit committed, byte-stable build/CI artifacts for a Python project instead
  of re-inferring the steps at runtime. `project-setup` writes a self-documenting **Makefile**
  from the detected toolchain (ruff, mypy/pyright, pytest, coverage) and package manager;
  `quality-gate` writes `scripts/quality-gate.sh` (`set -euo pipefail`; lint + type + test +
  coverage-threshold) as the single source of truth CI and `make check` both call, so local == CI;
  `deploy` writes a safety-railed `scripts/deploy.sh` (dry-run, confirmation gate, rollback,
  health-check retry, no inlined secrets). Detection is a pure function of observable inputs;
  targets/steps are omitted when a tool is absent (never fabricated), `pytest --cov` is only
  emitted when pytest-cov is a declared dependency (incl. PEP 735 `[dependency-groups]`), and
  user-supplied deploy values are shell-escaped against `$`/backtick/quote injection. Each skill
  ships a pure generator library + thin runner (with `--verbose` debug logging), a vendored
  byte-identical `validate_skill.py` (tracked by the skill-script drift guard), evals, and tests
  at the ≥95% branch-coverage floor (generated shell/Make artifacts are validated by real
  execution + ShellCheck, not just syntax). Registered in `skills/marketplace.yaml` with per-skill
  CI jobs (`skills-ci.yml`, py3.10–3.12). A root `Makefile` was generated by `project-setup`
  (dogfooding). Not converted: the inference-heavy `claude-foundation/skills/*`.
- **BrainTrust integration — Phase 2 (dataset source):** a `braintrust` dataset source
  (`@DATASETS.register("braintrust")`) that pulls a dataset via the SDK's `init_dataset` and maps
  each `DatasetEvent` (`id`/`input`/`expected`/`metadata`) onto the harness record shape. It is
  self-wiring (credentials from the environment) and **fail-fast** — it raises a clear install
  error when the `braintrust` SDK is absent, because a dataset is essential input and must not
  silently degrade to an empty eval (mirrors `ParquetDataset`). Verified against the installed
  `braintrust` 0.27 SDK; offline-tested via fake-`sys.modules` injection, with a live path and an
  LLM `autoevals` (`Factuality`) path in `tests/test_braintrust_live.py`. Adds the
  `datasets → braintrust_client` architecture edge. Managed-prompt fetch remains deferred (see
  `docs/braintrust-spike.md`): BrainTrust prompts are chat-message arrays, which don't map
  cleanly onto the harness's single-string judge-prompt seam. Formalized as feature **F-038**
  with an offline validation gate (`scripts/validations/F_038.py`).
- **BrainTrust integration — peer-review hardening:** an objective review pass added logging on
  the previously-silent paths (`autoevals` scorer failures now `logger.warning`; dataset fetch
  and sink export log counts; `build_client`/`flush` log at debug), extended the `AutoevalsScorer`
  fail-safe to cover result parsing, fixed a shared `_to_item` id-collision (a `None` id now falls
  back to the positional index instead of the string `"None"` — also fixing the latent Langfuse
  peer bug), aligned the dataset param to `project_name`, and consolidated the duplicated fake-SDK
  test doubles into shared `conftest.py` fixtures (with added assertions for `init` plumbing,
  the `min_value_to_log` boundary, scoreless items, and id-less records).
- **BrainTrust integration (additive, SDK-optional; Phase 1):** a `braintrust` result sink
  that exports each eval item to a BrainTrust *experiment* via the native `experiment.log`
  write-path (`input`/`output`/`expected` + a `{name: value}` scores dict per row), and an
  `autoevals` scorer that bridges BrainTrust's `autoevals` library into the `Scorer` contract
  (`Score`→`ScoreResult`, with skip/`None` and fail-safe handling). Both follow the reversible
  Phoenix-spike pattern: a new `braintrust_client/` seam (`NullBrainTrustClient` +
  injected-handle `SDKBrainTrustClient` + `build_client(enabled=…)` factory) that is a no-op
  when the SDK is absent or `enabled=False`, so existing runs and the offline suite are
  unaffected and `SCHEMA_VERSION` is unchanged. Shipped as two optional extras (`braintrust`,
  `autoevals`); `braintrust` stays out of the offline CI job while `autoevals` (lightweight,
  offline-safe heuristics) is installed there for real coverage. Credentials are read from the
  environment (`BRAINTRUST_API_KEY` / `BRAINTRUST_API_URL`), never hardcoded. Documented in
  `docs/braintrust-spike.md`; `architecture.yaml`/`.mmd` gain the `braintrust_client` component
  and the `sinks → braintrust_client` edge. (The dataset source and LLM-based autoevals scorers
  landed in the Phase 2 entry above; managed-prompt fetch remains the one deferred item.)
- **Project charter (`docs/CHARTER.md`) + drift guard:** a north-star governance document
  modelled on the drone-comms charter structure (Status & Purpose / Vision / Mission /
  Scope + non-goals + ratified amendments / Invariants / Roadmap / How-agents-use-it),
  synthesized from `README.md`, `AGENTS.md`, and `docs/decisions/*`. It ratifies what is
  already true and references drift-prone values (coverage floors, schema versions) at
  their source rather than restating them. A new `scripts/check_charter_drift.py` guard
  (stdlib-only, `_cli.configure_logging`, exit `0/1/2`) parses every markdown link target
  in the charter and asserts each local file/ADR reference resolves, skipping externals,
  anchors, and glob patterns to avoid false positives; covered by
  `tests/test_check_charter_drift.py`. The guard runs as a first-class step in
  `quality-gates.yml` (mirroring the sibling drift/size-budget guards) and is wired into that
  workflow's ≥85% tooling-coverage gate. `AGENTS.md` now lists the charter as the tier-0 read,
  and the C4 "Quality & Eval-Integrity Gates" diagram (`docs/c4_architecture.md`) lists the
  new guard. The drift-detected path now emits a `logger.warning` (parity with the
  usage-error/success paths) so CI surfaces it in structured logs. Hardening (review
  feedback): the guard rejects targets that escape the repository root (e.g.
  `../../etc/passwd`) as invalid even when the OS path exists — it validates *repo*
  references, not arbitrary filesystem paths — and F-031 matches the exact quoted
  `"scripts/validations"` TOML entry (tolerating single-line, multi-line, and string
  `mypy_path` forms via a `re.DOTALL` capture; still dependency-free for the Python 3.10
  gate) so a different path containing that substring cannot false-pass and a harmless
  multi-line reformat cannot break the gate.

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

### Fixed
- **`py.typed` mypy fallout — `mypy src/eval_harness` + 32 latent errors** (see
  [`docs/gap-analysis-2026-07-py-typed-mypy.md`](docs/gap-analysis-2026-07-py-typed-mypy.md)):
  shipping `py.typed` made mypy follow the editable-installed `eval_harness`, so
  `mypy src/eval_harness` failed with *"Source file found twice"* (`src.eval_harness.*` vs
  `eval_harness.*`) — a red already on `main@1fb53b9`. Fixed config-only by adding `src` to
  `[tool.mypy].mypy_path` (with the existing `explicit_package_bases`). Unblocking that CI step
  exposed 32 real type errors in `scripts/validations/F_018,F_021,F_024,F_025,F_026,F_027,F_030`
  and `tests/test_phoenix_{sink,cli}.py` that `py.typed` had surfaced (typed `eval_harness`
  reaching callers that passed loosely-typed dicts). Fixed with the repo's own idioms —
  `EvalConfig.model_validate({...})` for config construction, `assert isinstance(...)` /
  `is not None` narrowing, and reusable `_phoenix_sink`/`_null_client` test helpers — all
  behaviour-preserving (gates still exit 0). `mypy` (src/scripts/tests), `ruff`, and every
  package coverage floor are green.
- **`py.typed` now ships in the root wheel (PEP 561)**: `src/eval_harness/py.typed` was
  missing and there was no `[tool.setuptools.package-data]` stanza, so the root `eval_harness`
  package was not advertised as typed to downstream consumers (the sub-packages already shipped
  theirs). Added both; verified the built wheel contains `eval_harness/py.typed`.

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
- **`check_charter_invariants` / `check_size_budget`:** `Finding.detail`/`Finding.path`
  mixed `.as_posix()` with `str(path)` and raw f-string `Path` interpolation, both of which
  emit OS-native `\` on Windows — invisible in CI (Linux-only) because a native and a
  portable separator produce byte-identical strings there. All remaining sites in both
  gates now use `.as_posix()` uniformly; the corresponding tests assert the exact portable
  string (several previously checked only `Finding.kind`, so a regression back to
  `str(path)` would not have been caught).
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
