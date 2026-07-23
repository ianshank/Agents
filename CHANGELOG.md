# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.3.0-dev] — Unreleased

### Added
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
