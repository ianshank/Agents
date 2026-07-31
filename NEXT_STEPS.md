# Next Steps

## Recently Landed — Quality & Eval-Integrity Gates

- [x] **Merge-gate calibrator-health integrity (F-049, ADR 0029)** — an independent
  re-verification of `docs/gap-analysis-merge-gate-2026-07-24.md`
  (`openspec/changes/merge-gate-health-integrity/review.md`) confirmed its G1/G2/G3 but found
  G3's stated mechanism wrong, its severity understated, and three defects it never named.
  The gate's fourth health floor could pass having measured nothing: `_upper_half_ci_width`
  accumulated into a `0.0` initialiser over bins above raw 0.5, so a domain whose audits all
  sat below that returned the identity of a `max`-reduction and satisfied `max_bin_ci_width`
  vacuously — **reproduced to `AUTO_MERGE` under stock config**. It also measured the raw
  score while `decide()` gates on the calibrated `p`. `_operating_bin_ci_width` now defines
  the region by the per-decision Wilson floor (tau-free, since `tau` is derived *from*
  health) and returns `None` when nothing qualifies, which `is_trustworthy` rejects.
  `GatePolicyConfig` gains bounds on all nine tunables plus CLI flags, supplying the seam
  behind ADR 0005 §3's long-standing promise of a human-set `risk_target`; the bin count and
  score→bin routing are each single-sourced; and `min_calibration_n` now floors the held-out
  fold rather than the both-fold total that overstated it 2×. Decision-neutral on the live
  store (0 `HUMAN_AUDIT` records ⇒ permanent cold-start `ESCALATE`), which is why it landed
  before activation rather than after. **Still open:** wiring the workflow to the new flags
  (decision-changing the moment a repo variable is set), and the risk-appetite decision on
  `max_bin_ci_width` — under honest measurement it may keep the gate closed until every
  eligible bin holds ~50+ high-accuracy audits.

- [x] **Charter alignment audit + fixes + `check_charter_invariants.py` gate (PR #114)** —
  a multi-agent audit (`docs/CHARTER_ALIGNMENT_AUDIT.md`) mechanically re-verified every
  claim in `docs/CHARTER.md` against the code and found 5 real drift items: `Judge`/
  `DatasetSource`/`TargetRunner`/`ResultSink` were `abc.ABC` (now `typing.Protocol`; `Scorer`
  stays `ABC` — see below), no `Clock` DI seam existed (added
  `agent_core.protocols.Clock`/`SystemClock`/`FixedClock`, wired through `audit_sampler`/
  `merge_seed`/`outcome_labeller`/`merge_gate_ci`), `ModelTarget` hardcoded operational
  defaults (added `ModelTargetConfig`, now validated at construction time), `HARNESS_SPEC.md`
  described a stale single-package project, and the `claude-foundation` staging directory's
  rationale was undocumented (added [ADR 0028](docs/decisions/0028-claude-foundation-staging.md)).
  Added `scripts/check_charter_invariants.py` — a new CI gate that mechanically re-checks
  these claims going forward — so this class of drift doesn't require another manual audit.
- [x] **Merge-conflict marker guard + F-048 ledger correction** — removed four orphan
  `>>>>>>> origin/main` markers (`NEXT_STEPS.md`, `AGENTS.md`, `CHANGELOG.md` ×2) left by a
  clean merge that had silently discarded content; added an inline sweep to
  `quality-gates.yml`'s `gates` job so a marker in any tracked file now fails CI. Also flipped
  F-048 (gitleaks, landed via #83) from `in_progress` to `done` with its `implemented_in` SHA,
  so `F_048.py` is actually enforced by `validate.py --tier fast` going forward.
- [x] **Hardened matrix eval tools test suite** — eliminated fragile `try...except pass` swallows and hard-coded mocks in `tests/test_matrix_eval_tools.py`, replacing them with full offline dependency injection.
- [x] **Reasoning & Planning Skills** — added three composable reasoning skills to the marketplace (`hierarchical-recursive-brainstorm`, `openspec-quality-plan`, `openspec-peer-review`).
- [x] **Dynamic drift guard script tech-debt resolution** — resolved tech debt in the dynamic drift guard scripts.
- [x] **Proxy-correlation measurement, PPI++ report estimator & audit propensity (F-047,
  ADR 0026)** — an external critique proposed swapping the gate's Wilson interval for
  PPI++. The peer review
  (`openspec/changes/eval-proxy-and-estimator/review.md`) verified its arithmetic and
  citations but found it aimed at the wrong lever: PPI++ on the calibrated-confidence proxy
  buys only ~1.05–1.1× effective-N at the system's own `min_auroc=0.65` floor, and ~0 on the
  *conditional* subsets the gate operates over (restriction of range). Measured on a
  synthetic soak, changing the **proxy** was worth 1.63× where changing the **estimator**
  was worth 1.08×. So `agent_core.proxy_eval` now measures proxy↔audit correlation
  marginally *and* conditionally, `agent_core.ppi` adds a fail-closed prediction-powered
  interval (`--estimator ppi++`, report-only — the gate still uses Wilson), and
  `selection_propensity` is recorded end-to-end so audits can later be reweighted by `1/p`.
  Six defects found by adversarial review *after* the code was fully covered are pinned by
  regression tests. **Still open:** nothing consumes the propensity yet (aggregates are
  reported as unweighted), and the dated proxy-correlation snapshot waits on real data —
  the live store still holds 0 `human_audit` rows.

- [x] **Merge-gate fail-open fixes + peer review of the agent-record decontamination plan** —
  a peer review of the 2026-07-24 draft plan (`docs/plans/agent-record-decontamination/`, whose
  corrected v2 supersedes it) turned up three verified defects, each reproduced before being
  fixed. A confidence of `NaN`, `inf`, or anything above 1.0 was routed to the *top* calibration
  bin and scored as maximum confidence, so `decide()` returned `AUTO_MERGE` for garbage — latent
  only because every domain is still cold-start, i.e. it would have activated exactly when the
  gate went live. `evaluate_calibration` let an *undefined* AUROC satisfy the discrimination
  criterion vacuously, so a forecaster wrong 100% of the time passed the ship gate. And
  `build_domain_models` decided per-domain autonomy with no log at all, making an all-passive
  store indistinguishable from an empty one. Guards are config-driven
  (`CalibrationConfig.min_eval_samples` / `require_discrimination`) and default to the prior
  behaviour, so no existing verdict changes. A fourth defect found in the same sweep is closed
  by [ADR 0025](docs/decisions/0025-outcome-record-forward-compatibility.md): `store_sync`
  preserved records from a newer writer that `OutcomeStore` then refused to parse, so an
  ordinary version skew would have failed every PR. Nine further findings are ranked with
  reproductions in `docs/gap-analysis-merge-gate-2026-07-24.md`.
- [x] **Agent-record calibration: routing + proxy confidence + report (F-042/F-043/F-044, ADR 0023)**
  — closed the agent-record calibration gap. Previously every merge-gate record was
  `agent_version:null` / `domain:human/*` / `raw_confidence:0.0`, so the agent-domain predictor was
  degenerate by construction. Now the seed-on-merge workflow routes agent changes (PR head-ref
  prefix, `config/agent-authors.yaml`) into the agent domain with a **deterministic proxy
  confidence** (`scripts/agent_confidence.py` — diff size / files / test-ratio / protected-path,
  sigmoid-mapped, no network) and the real `agent_version`; `agent_core.calibration_report` reports
  ECE/Brier/AUROC/abstention (Wilson CIs) over the agent slice, honest `DEGENERATE` guard, surfaced
  to the daily labeller summary; and a one-off reversible backfill
  (`scripts/migrations/agent_domain_backfill.py`) re-attributes historical agent SHAs. Hardening
  follow-up ledgered as **F-046** (fail-safe routing, single-sourced `agent_core.domains`,
  `ReportConfig`, shared `scripts/_config.py`, strict parse, migration coverage). This is the
  agent-confidence artifact the merge-gate soak item was waiting on. Remaining: accumulate the
  agent-domain HUMAN_AUDIT labels (the corpus now grows on every agent merge) before any agent
  domain can leave cold-start ESCALATE.
- [x] **Skill Validation Assertion Registries & dataset-lint (F-045)** — Re-architected `validate_skill.py` to decouple assertion grading from validation loops using the `ASSERTION_GRADERS` registry (detailed in [ADR 0024](docs/decisions/0024-assertion-graders-registry.md)). Introduced a standalone `dataset-lint` skill capable of format-agnostic deep validation. Brought both components up to 100% test coverage and captured comprehensive testing matrices into `eval_test_matrix.xlsx`.
- [x] **Merge-gate soak-stats (F-040)** — `agent_core.store_sync.soak_progress(records, target)`
  makes progress toward the ADR 0005 enablement threshold observable: a pure, read-only summary
  (total/pending/labeled, HUMAN_AUDIT count, per-domain cold-start keyed on
  `AuditConfig.per_domain_floor`, n-vs-target, merge velocity/day, days-to-target) plus an opt-in
  `store_sync stats --soak-target N` that adds a reserved `_soak` block (bare-stats output
  byte-identical). No TCB edit, no store mutation (property-tested), no schema bump. `target` is
  a caller-supplied counter, not a claim about the real activation bar — per the corrected soak
  framing below, that bar is ~380 near-perfect audited records per domain, not `N≥20`. Soak
  enablement itself stays time-gated (real bar reached + ≥1 human verdict + weekly audits).
- [x] **Public-surface backwards-compat guard (F-039)** — `tests/test_public_surface.py`
  freezes every package's public `__all__` exports (exact-equality vs a committed
  baseline), so a removed/renamed export now fails CI instead of silently breaking every
  config/import that used it. Duplicated byte-identically into all 5 packages'
  `tests/` dirs, drift-guarded against the root canonical. Surfaced and closed a
  pre-existing, independent gap while landing: `scripts/eval_protected_paths.py`'s
  `"tests/**"` pattern only anchored the root suite, leaving all 4 sibling packages'
  entire test suites without protected-path/CODEOWNERS coverage — both now fixed.
  A companion **plugin-registry surface guard** (freezing the config-selectable
  datasets/judges/scorers/sinks/targets keys + aliases — the compat surface `__all__`
  can't see) is in a separate PR.
- [x] **CI gate delegation phase-2 POC (ADR 0021) — `eval-harness-ci` → `make check`** — a new
  reusable composite action `.github/actions/run-quality-gate` (setup-python + install + run the gate)
  now backs `eval-harness-ci.yml`, which delegates to the root `make check` instead of duplicating
  ruff/format/mypy/pytest inline. CI == local `make check` for this workflow. First of ADR 0021's six
  workflows; the rest (`agent-core`, `flow-corpus`, `behavioral-regression`, `claude-foundation`,
  `skills-ci`) follow as separate label-gated PRs, then ADR 0021 flips Proposed→Accepted. Surfaced for
  review: the root gate's `ruff check .` makes this job lint the whole repo (currently green); the
  py3.12 `htmlcov/` artifact was dropped (not produced by the shared gate). Both files are under
  protected `.github/**`, so the PR carries the `eval-change-approved` label gate.
- [x] **E2E Windows cross-platform hardening (21/21 offline green)** — fixed
  three classes of failure on the Windows e2e path: (1) a pre-existing PS 5.1
  string-concatenation bug in the `--junitxml` argument that silently zeroed
  test collection, (2) WSL bash path-mangling (exit 127) and symlink-privilege
  denial (WinError 1314), (3) F-038 sys.path gap when running standalone
  validation scripts with a stale editable install.
- [x] **Eval-backend validation experiment scaffolded (`experiments/backend-validation/`)** —
  the full offline implementation of `eval-backend-validation_v1` (Langfuse vs Opik
  capability validation for the eval-backend displacement decision) landed as an isolated,
  dependency-only subtree: L1/L2/L3 probe layers, six phases with fail-safe BLOCKED/HALT
  discipline, digest-pinned compose stacks, ops-burden metrics, a human-signed rubric (TCB),
  and its own generated quality-gate (196 tests, ≥95% branch coverage, mypy strict). Ships
  **unsigned** — no probe executes until a human corrects the transcribed matrix claims,
  signs `PROBES.yaml` + `RUBRIC.md`, and writes the `SIGNOFF` hash file (agents never sign).
  Remaining (human-driven, outside this repo's CI): resolve `CLAIM_TBD` marks from the
  external matrix and sign the TCB; `make pin-digests` where the registries are reachable;
  run P1–P5 against live stacks; commit the `reports/`. Deliberately NOT wired into the root
  `Makefile` fan-out (the experiment is temporary, and the makegen Makefile has no
  hand-extension seam so a delegation target would not survive regeneration) — use
  `make -C experiments/backend-validation check`. Optionally, a path-filtered CI workflow can
  ride the later protected batch (a new `.github/workflows/*.yml` is label-gated).
- [x] **Determinism phase P1+P2: workspace gates dogfooded (skills → 1.1.0)** — the
  generators grew monorepo support (`--workspace` fan-out; repeatable `--lint-path`/
  `--typecheck-path`; multi-source `--cov=`; provenance header; hand-extension marker with a
  `do_extra()` hook) and the repo now runs on the results: `./scripts/quality-gate.sh all`
  is the root gate (lint + 3 mypy runs + cov ≥96 + the F-031 scripts gate below the marker),
  each sibling package has its own generated gate + Makefile, and `make check-all` runs all
  six green locally. ruff/mypy pins unified across all four previously-floating package dev
  extras. P3 (ADR 0022 + `plan`/`test-first`/`code-review` gate delegation) and P4 (C4
  runtime-vs-import semantics ownership in `docs/c4_architecture.md`, `behavioral_regression`
  L2 coverage, c4-docs manifest-deference contract) landed in the same PR. Remaining: P5 —
  the labeled protected batch (ADR 0021: rewire the 4 per-package workflows to the gate
  scripts; `architecture.yaml` comment fix + unused-edge removal + `.mmd` regen; drift
  workflow path filter; PROTECTED_PATTERNS/CODEOWNERS additions; cross-reference ADR 0021
  in ADR 0022's Related list). Review-round deferrals worth a future gategen minor: (a)
  single-instrumented-run coverage — the root gate's `all` runs the suite twice (harness
  cov + F-031 scripts cov); one run + two `coverage report` passes over shared data would
  halve gate wall-clock but needs a combined run-config design; (b) individually
  dispatchable named hand-steps (today `do_extra` is reachable only via `all`), which
  would let CI call granular hand extensions without duplicating their commands.
- [x] **Deterministic generator skills — `project-setup` / `quality-gate` / `deploy` (ADR 0020)** —
  three skills that emit committed, byte-stable artifacts (a Makefile; a `set -euo pipefail`
  quality-gate script that CI and `make check` share so local == CI; a safety-railed deploy
  scaffold with dry-run/confirm/rollback/health-check) instead of re-inferring the steps at
  runtime. Detection is pure; nothing is fabricated (targets/steps omitted when a tool is absent;
  `pytest --cov` only when pytest-cov is declared); deploy values are shell-escaped. Registered in
  `marketplace.yaml` with per-skill CI (`skills-ci.yml`, py3.10–3.12) at the ≥95% coverage floor;
  a root `Makefile` was generated by dogfooding `project-setup`. Follow-ups: optionally wire the
  repo's own `quality-gates.yml` to a generated `quality-gate.sh`; add per-package targets to the
  root Makefile for the monorepo; consider converting the deterministic parts of the
  inference-heavy `claude-foundation/skills/*`.
- [x] **BrainTrust integration (F-038, additive/SDK-optional; Phases 1–2)** — a `braintrust`
  result sink (per-item `experiment.log`), a `braintrust` dataset source (`init_dataset`), and an
  `autoevals` scorer bridge, all behind a new `braintrust_client` seam
  (`NullBrainTrustClient` / injected-handle `SDKBrainTrustClient` / `build_client` /
  `fetch_dataset_items`) that no-ops when the SDK is absent or disabled — `SCHEMA_VERSION`
  unchanged, offline suite unaffected. Verified against the installed `braintrust` 0.27 SDK;
  offline-tested via fake-`sys.modules` injection with a live path in `tests/test_braintrust_live.py`.
  Credentials come from `BRAINTRUST_API_KEY` / `BRAINTRUST_API_URL` (env only). `braintrust` stays
  out of the offline CI job (no-op precedent from Phoenix); `autoevals` (lightweight, offline-safe
  heuristics) is installed in CI for real coverage. See `docs/braintrust-spike.md`.
  Follow-ups: managed-prompt fetch (BrainTrust chat-prompt → single judge-string is lossy — needs a
  design decision) and an opt-in `braintrust-live.yml` workflow mirroring `phoenix-live.yml`.
- [x] **One-command E2E / user-journey harness + Windows portability** —
  `scripts/run_all_e2e.ps1` (+ `docs/e2e-runbook.md`) runs every package suite, every
  `features.yaml` gate, every package CLI journey, and the skill/hook e2e tests in one
  command, with credential-gated live-integration tiers. Shaking the whole tree out on
  Windows surfaced and fixed six cross-platform defects (byte-oriented `store_sync` git
  plumbing; `foundation_tools` posix-path findings; a YAML-escaped path in the drift e2e
  test; hermetic Phoenix optional-dependency tests; a symlink test that skips without the
  privilege; and `validate_skill.py` running evals under the venv interpreter with
  cross-platform eval commands). Baseline offline result: **20 pass / 0 fail**. See the
  CHANGELOG "Windows / cross-platform portability" entry. Follow-ups: wire the harness into a
  nightly CI job, and pin the eval-corpus-forge golden values so they match on Windows too.
- [x] **Live Phoenix validation (opt-in)** — `.github/workflows/phoenix-live.yml`
  (`workflow_dispatch`) validates the reversible Phoenix spike end-to-end on a
  networked runner: `dep-resolve` runs `pip install '.[phoenix,phoenix-evals,parquet]'
  --dry-run` to confirm pandas/numpy vs the `pyarrow>=14,<20` pin, then `live` boots
  `arize-phoenix==17.18.0` via `phoenix serve` and runs `tests/test_phoenix_live.py`
  against the real OTLP collector + Phoenix evals judge. Both jobs have
  `timeout-minutes: 20`; all mutable identifiers (project name, span name, judge
  name, eval model) are env-driven with defaults. Offline suite unaffected (the
  seam degrades to a no-op when the SDK is absent). Rollback: see
  `docs/phoenix-spike.md`.
- [x] **Real-data activation (F-032…F-035, ADR 0018)** — the calibrated merge gate now
  runs on real data: the outcome store persists on the `merge-gate-data` branch
  (`agent_core.store_sync`, F-032), a daily labeller resolves matured records with
  passive labels behind an anti-optimism precondition guard (F-033), a shadow gate
  logs a decision on every PR plus a `human/<domain>` observability decision and
  seed-on-merge writes one pending record per push to main (F-035), and a weekly
  audit queue + human-triggered verdict dispatch is the only writer of HUMAN_AUDIT
  labels (F-034). The agent-confidence seam this left open is now filled by F-042
  (see above); F-036 (real-transcript corpus bridge) stays recorded as deferred.
  Human checklist before the soak counts: add the `eval-change-approved` label to
  the activation PR (protected paths); exclude `merge-gate-data` from branch
  protection; enable required reviewers on the `merge-gate-verdict` environment;
  record the first verdict via the dispatch UI.
- [ ] **Merge-gate tech debt (`docs/gap-analysis-merge-gate-2026-07-24.md`)** — the three
  HIGH findings (G1 `GatePolicyConfig` unreachable/unvalidated, G2 the duplicated binning
  implementations, G3 `_upper_half_ci_width` returning `0.0` for "no data") are **closed by
  F-049/ADR 0029** above, along with three defects the analysis never named. Re-verification
  also **refuted G5**'s headline claim — `outcome_labeller` and `audit_sampler` both gained
  real logging since the doc was written — leaving its `record_verdict` non-idempotency
  sub-claim, which the library docstring says is deliberate.
  Remaining, none of which can change a gate decision: **G4**, widened by that
  re-verification from 2 CLIs to 4 (`calibration_report`, `merge_seed`, `outcome_labeller`
  and `audit_sampler` all log at INFO but never call `configure_logging`, so every structured
  run record is discarded at the root default WARNING); **G6** `load_yaml_mapping -> dict`
  erasing types at three call sites; **G7** two `configure_logging` implementations with
  different signatures and formats, of which `scripts/_cli` is the one `AGENTS.md` names as
  canonical; **G8** two provably dead lines in `IsotonicCalibrator.predict` counted against
  the coverage budget; **G9** `agent_confidence.py` missing from `quality-gates.yml`'s
  explicit `--cov=` allowlist, so the module computing every `raw_confidence` is gated in one
  job and not the other.
- [ ] **Merge-gate soak** — accumulate shadow decisions and weekly audits before
  revisiting the ADR 0005 enablement checklist. **The "N≥20" this entry used to quote is a
  soak *counter*, not the activation bar**: the peer review in
  `openspec/changes/eval-proxy-and-estimator/review.md` establishes that `tau` is gated by
  a four-gate Wilson stack whose binding term (`threshold_for_risk` at `risk_target=0.02`,
  measured on a held-out fold) needs roughly **380 near-perfect audited records per
  domain**. Treat N≥20 as "enough to publish an honest first report", never as "enough to
  enable auto-merge". The agent-confidence artifact that
  blocked agent domains now exists (F-042: `scripts/agent_confidence.py` feeds
  `merge_gate_context.py --confidence`), so agent merges are seeded with a real varying
  proxy confidence and the agent-domain corpus is non-degenerate; the remaining gate for
  an agent domain leaving cold-start is accumulating its HUMAN_AUDIT labels, not the
  predictor. (F-036, the real-transcript corpus bridge, stays deferred — it is an
  independent enrichment, not a blocker.)
- [x] **Operational-scripts quality gates (F-031)** — closed the 2026-07 gap analysis
  (`docs/gap-analysis-2026-07.md`): `scripts/` is now lint/type-enforced in `eval-harness-ci`
  with its own ≥85% coverage gate (`scripts/.coveragerc`); 46 new tests for `validate.py` /
  `select_next.py` / `init.py`; `resolve_repo` fixed to be immune to git `url.insteadOf`
  rewrites; `scripts/validations/F_031.py` guards the enforcement itself.
  **2026-07-21 incident + fix:** ADR 0021's CI-delegation (PR #64) moved the enforced
  commands from inline workflow YAML into `scripts/quality-gate.sh`, which broke `F_031`'s
  (and `F_037`'s) inline-string assertions even though the underlying enforcement stayed
  intact — undetected because `quality-gates.yml` didn't run on the `.github/`-only PR. PR
  #65 repointed both validators at the delegated behavior (`_common.ci_enforces`) and
  widened the trigger path filter so this class of regression can't hide again; both have
  passed on `main` since PR #65 merged (2026-07-21).
- [x] **`claude-foundation` plugin plan** — peer-reviewed, corrected execution plan for the
  reusable Claude Code plugin repository (`docs/plans/claude-foundation/`). Planning only;
  see follow-ups below.
- [x] **Execute `claude-foundation` M0–M6 (staged)** — full plugin implemented per
  `docs/plans/claude-foundation/PLAN.md` in the staging directory
  [`claude-foundation/`](claude-foundation/): manifests (official `claude plugin validate`
  green), 4 skills with evals, 2 subagents, 3 hooks (fail-closed guard, fail-open
  verify/logger), `foundation_tools` validation/scan/eval-gate package (94% branch
  coverage, mypy strict), inert CI workflow, docs+ADRs. Verified end-to-end via
  `claude --plugin-dir` headless load. Staging is CI-neutral here (per ADR 0017 the
  plugin's final home is its own repo).
- [ ] **Extract `claude-foundation/` to its own repository** — create
  `ianshank/claude-foundation`, move the staging directory (history via
  `git filter-repo` or fresh import), activate its CI, tag v1.0.0, then run the M7
  dogfood (config-only install here per ADR 0017).
- [x] **`claude-foundation` M7 reconciliation ADR** — decided in
  [ADR 0017](docs/decisions/0017-claude-foundation-reconciliation.md): this repo keeps its
  4 domain skills and custom marketplace unchanged; foundation supplies only the generic
  layer, consumed by installing the plugin (pinned tag), never by vendoring. Routing rule:
  generic skills → foundation, domain skills (anything importing `eval_harness`/`agent_core`
  or gated by this repo's CI) → here. M7 dogfooding is config+docs only, unblocked once the
  plugin tags v1.0.0.
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
- [ ] **Consider migrating `Scorer` to `Protocol`** — the other four core interfaces
  (`Judge`/`DatasetSource`/`TargetRunner`/`ResultSink`) are `typing.Protocol`; `Scorer`
  stays `abc.ABC` because `typing.Protocol.__init__` doesn't reliably propagate a Protocol
  base's own `__init__` to subclasses that don't redefine their own on Python 3.10 (fixed in
  3.11+), and `pyproject.toml`/`agent-core/pyproject.toml` both pin `requires-python >= 3.10`.
  Revisit once the floor moves past 3.10 (see `src/eval_harness/core/interfaces.py`'s module
  docstring for the confirmed regression).
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
  Root `eval_harness` marker + `[tool.setuptools.package-data]` added so the wheel
  actually carries it (the sub-packages already shipped theirs).

## Medium Term (v1.3.0)

- [x] **Skill Marketplace** — Centralized registry for community-contributed
  skills with versioned SKILL.md validation (F-023: `skills/marketplace.yaml` +
  schema + `scripts/skill_marketplace.py`, reusing `validate_skill.py` read-only).
- [x] **Skills brought up to date** — `openai-judge` (the last old-convention
  skill) modernized to the v2.0 standard: `tests/` with a ≥95% coverage gate,
  `ruff.toml`, `validator_version: '2.0'` frontmatter, and a dedicated
  `skills-ci.yml` job (F-028, ADR 0014). All skills now share one bar.
- [x] **model-bench marketplace skill** — packages multi-model comparison
  (F-024) and A/B campaigns (F-025) as a discoverable skill that thinly forwards
  to the `eval-harness compare`/`campaign` CLI; offline echo fixtures, drives
  real models via the F-027 target (F-029, ADR 0015).
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
