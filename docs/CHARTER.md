# Project Charter — langfuse-eval-harness (stable long-term plan)

## Status & Purpose

This document is the north-star reference for humans and AI agents working in this
repository. It changes rarely and only through deliberate decision. Day-to-day work lives
in [NEXT_STEPS.md](../NEXT_STEPS.md); operational orientation for coding agents lives in
[AGENTS.md](../AGENTS.md); install/test/gate commands and the requirement-to-mechanism map
live in [README.md](../README.md); architecture lives in
[architecture.mmd](../architecture.mmd), [architecture.yaml](../architecture.yaml), and
[docs/c4_architecture.md](c4_architecture.md); the record of individual decisions lives in
the Architecture Decision Records under [docs/decisions](decisions). Tasks that would
require a charter modification — expanding scope (§3) or relaxing an invariant (§4) — are
escalated for human decision rather than implemented unilaterally (§6).

## 1. Vision

A dynamic, modular, backwards-compatible enterprise **LLM evaluation harness**: operators
run offline-first, deterministic evaluations of language-model behaviour, wire in real
observability and judge backends only when they want them, and trust that the evaluation
itself cannot be silently weakened. Components — judges, scorers, sinks, datasets,
transports — are added by third parties through registries and entry points, never by
editing the core. Every external integration (Langfuse, Phoenix, OpenAI, Anthropic,
Bedrock) sits behind a narrow, reversible seam so the offline suite always runs with zero
external dependencies. See [README.md](../README.md) for the canonical statement of purpose.

## 2. Mission

Deliver and maintain a monorepo of five Python packages plus vendored skills and CI, each
with a single clear role (authoritative table in [AGENTS.md](../AGENTS.md)):

- **`eval_harness`** (root) — the LLM evaluation harness with pluggable judges, scorers,
  sinks, and datasets, and first-class Langfuse/Phoenix integration behind SDK-optional
  seams.
- **`agent-core`** — a deterministic control & calibration core with zero runtime
  dependencies: the two-gate verifier loop, the per-run cost budget, and the calibration
  measurement stack, exposed through typed `Protocol` seams.
- **`behavioral-regression`** — a calibrated, offline `ship / hold / escalate` gate that
  detects a contested behavioural regression between two model versions and proves its own
  judge is not fooling itself.
- **`flow-corpus`** — a calibrated corpus of agentic flow variants: specimens, task suites,
  oracles, and the validation runner (offline + deterministic).
- **`flow-protocol`** — the versioned contract surface between the flow-calibration corpus
  and the validation harness.

Operational tooling and the quality gates live under `scripts/`; domain skills are vendored
under `skills/` and registered via the skill marketplace.

## 3. Scope

**Included:** the root `eval_harness` package and its plugin surface (judges, scorers,
sinks, datasets, targets); the four sibling packages above; the operational tooling and
quality gates under `scripts/`; and the vendored skills under `skills/`.

**Excluded (non-goals):** each boundary below is either already stated in the repo (cited)
or follows directly from the project's identity as an evaluation harness, and is ratified
here so it is not re-litigated per change.

- **Not a training / fine-tuning / RLHF pipeline.** The harness measures model behaviour; it
  does not produce or update model weights — this follows from its identity as an
  *evaluation* harness ([README.md](../README.md), [AGENTS.md](../AGENTS.md)).
- **Gates never run live evaluations.** The regression gate is diff-only and never runs
  live-judge / Langfuse evals (see [README.md](../README.md), F-006).
- **The auto-fix loop ships disabled.** It is intentionally design-only scaffolding, not
  wired into CI (see [ADR 0004](decisions/0004-auto-fix-loop.md)).
- **Auto-merge is off by default.** The calibrated merge gate ships its decision logic
  inert; it merges nothing unless explicitly enabled by an environment flag (see
  [ADR 0005](decisions/0005-calibrated-merge-gate.md)).
- **`claude-foundation` is consumed as a pinned plugin, never vendored.** The generic
  foundation layer is installed at a pinned tag, not copied into this tree (see
  [ADR 0017](decisions/0017-claude-foundation-reconciliation.md)). Until it is extracted
  to its own repository (§5 roadmap), it is built and CI-verified in-tree as a
  self-contained, self-terminating staging directory — the sanctioned interim mechanism
  for reaching that end state, not an exception to it (see
  [ADR 0028](decisions/0028-claude-foundation-staging.md)).
- **`SCHEMA_VERSION` bumps are out of scope for feature branches.** They happen only in
  dedicated release commits with migration code (see [AGENTS.md](../AGENTS.md)).
- **No permissive config parsing.** `from_dict` is strict; unknown keys raise, no fallbacks
  (see [AGENTS.md](../AGENTS.md)).
- **The offline suite depends on nothing external.** SDK-optional seams keep the offline
  path free of network, SDKs, radios, or live servers.

This remains an evaluation harness, not a model trainer, an autonomous merge bot, or a
general observability platform.

### Ratified Amendments

An append-only log of deliberate, additive scope decisions. Each shipped behind
Protocol/registry/config seams with explicit defaults, leaving `SCHEMA_VERSION` and old
configs untouched.

- **Calibrated auto-merge gate (opt-in, default-off):** ship the decision logic and stores;
  auto-merge stays off by default — [ADR 0005](decisions/0005-calibrated-merge-gate.md).
- **Langfuse judge-prompt management (opt-in, YAML fallback):** additive optional prompt
  source — [ADR 0010](decisions/0010-langfuse-prompt-management.md).
- **Multi-model comparison (additive, opt-in):** old configs parse untouched —
  [ADR 0011](decisions/0011-multi-model-comparison.md).
- **A/B eval campaigns with statistical significance (additive, opt-in):**
  [ADR 0012](decisions/0012-ab-eval-campaigns.md).
- **Real model-backed target (additive, opt-in):** `target.type='model'` via params —
  [ADR 0013](decisions/0013-model-backed-target.md).
- **Time-windowed judge rate limiting (additive, opt-in):** optional sliding-window limiter
  — [ADR 0016](decisions/0016-time-windowed-judge-rate-limit.md).
- **Merge-gate outcome-store persistence:** backend is a dedicated orphan data branch —
  [ADR 0018](decisions/0018-outcome-store-persistence.md).
- **Structural size-budget enforcement:** complexity and file-length limits gated,
  function/method limits warn — [ADR 0019](decisions/0019-size-budget-gate.md).
- **Agent evaluation may extend the core models and the engine loop (additive, default-off):**
  trajectory, repeated-run reliability and environment-state evaluation need a field on
  `TargetOutput` and an attempt-aware item loop, which §4 invariant 1 otherwise forbids. Amended
  narrowly and under written compatibility obligations (append-only fields, no freezing, untouched
  `SCHEMA_VERSION`, regenerated surface baselines); the `eval_harness ⇎ flow_corpus` airgap is *not*
  amended — [ADR 0031](decisions/0031-additive-core-model-extension-for-agent-evaluation.md).

## 4. Invariants (enforce in review)

The non-negotiable constraints, every one enforced by CI (authoritative list in
[AGENTS.md](../AGENTS.md)). Values that could drift are **referenced at their source, not
restated here.**

1. **Open/closed extensibility.** New judges, scorers, sinks, datasets, targets, and state
   adapters are added through registries / the `eval_harness.plugins` entry-point group; the engine, core
   models, and registries themselves stay unmodified. One documented exception: agent-evaluation
   capabilities may extend the core models and the engine's item loop *additively*, under the
   compatibility obligations in
   [ADR 0031](decisions/0031-additive-core-model-extension-for-agent-evaluation.md) (§3 Ratified
   Amendments). The registries themselves remain unmodified either way, and every new evaluator is
   still a registered component.

2. **Versioned, backward-compatible surface.** `SCHEMA_VERSION` is single-sourced (see
   [src/eval_harness/version.py](../src/eval_harness/version.py)); the migration chain
   upgrades old configs on load (see
   [src/eval_harness/config/migrations.py](../src/eval_harness/config/migrations.py));
   registry aliases keep renamed components resolving. Documented compat shims are removed
   only via a deprecation ADR.

3. **Dependency injection via Protocol.** Judge/Sink/DatasetSource/TargetRunner/Clock and
   the SDK-optional client seams are structural; unit tests use fakes needing no network,
   SDKs, or live servers (see [AGENTS.md](../AGENTS.md)). All six core interfaces —
   `Scorer`/`Judge`/`DatasetSource`/`TargetRunner`/`ResultSink`/`StateAdapter` — are
   `typing.Protocol`. The first five converted as of `d4dc07f`; `Scorer` was the last of
   those five to convert: the historical blocker was that
   `typing.Protocol.__init__` does not reliably propagate a Protocol base's own `__init__` to
   subclasses that don't redefine their own on Python 3.10 (it has a concrete, inherited
   `__init__` the other four don't — the shared `name`/`default_name` bookkeeping every
   built-in scorer relies on). This repo's CI matrix moving to 3.11+ (ADR 0034) cleared that
   blocker, and the conversion has since landed (see
   [src/eval_harness/core/interfaces.py](../src/eval_harness/core/interfaces.py)).
   `StateAdapter` (F-060) joined later as a `Protocol` from the start, with no migration
   story of its own.

4. **Stateful I/O lives in the narrow seams, not the pure components.** SDK/network I/O is
   confined to the client seams; scorers and codecs stay pure per-item maps.

5. **Config-driven, no magic numbers.** Every operational value is a `*Config` field with a
   documented default; no hard-coded numeric defaults at call sites.

6. **Quality gates are non-negotiable.** `ruff`, `ruff format`, `mypy`, and the offline
   pytest suites stay green at their per-package coverage floors (defined in each package's
   [pyproject.toml](../pyproject.toml) and [scripts/.coveragerc](../scripts/.coveragerc), not
   copied here); the regression, protected-path, drift, and size-budget gates stay green.
   Each floor's *minimum value* — not just its existence — is pinned in
   [coverage-floors.yaml](../coverage-floors.yaml) and enforced by
   [scripts/check_coverage_floors.py](../scripts/check_coverage_floors.py): every source that
   declares one, plus the Makefiles that invoke it, is a protected path, so lowering a floor
   is a reviewed act rather than a quiet edit.
   [scripts/check_charter_invariants.py](../scripts/check_charter_invariants.py)
   mechanically re-checks this charter's own claims (package roles, zero-dep agent-core,
   `SCHEMA_VERSION` single-sourcing, coverage floors, Protocol-based DI, default-off flags)
   against the code on every change, so drift like the kind
   [CHARTER_ALIGNMENT_AUDIT.md](CHARTER_ALIGNMENT_AUDIT.md) found does not require
   another manual audit to catch.

7. **No secrets, no machine fingerprints in the repo.** Credentials come from environment
   variables only; the canonical set is [.env.example](../.env.example). Nothing host-specific
   is committed.

**Eval integrity.** Because the cheapest way to make a check "pass" is to weaken the
evaluation itself, evaluation-defining paths are protected: changes under them require a
human-reviewed `eval-change-approved` label. The single source of truth for the protected
set is [scripts/eval_protected_paths.py](../scripts/eval_protected_paths.py).

## 5. Long-term roadmap (themes, not dates)

Forward-looking themes only; concrete, changeable to-dos live in
[NEXT_STEPS.md](../NEXT_STEPS.md).

- **Merge-gate maturation → enablement.** Soak shadow decisions and accumulate human-audit
  labels before enabling the calibrated auto-merge gate. The agent-confidence artifact this
  once waited on now exists (`scripts/agent_confidence.py`, F-042/ADR 0023); the remaining
  precondition is accumulating each agent domain's HUMAN_AUDIT labels past cold-start.
- **Extract `claude-foundation` to its own repo.** Stand up the generic foundation layer as a
  pinned, installable plugin, then dogfood it config-only per
  [ADR 0017](decisions/0017-claude-foundation-reconciliation.md).
- **Make quality gates required checks.** Promote the quality-gate jobs to branch-protection
  required status once soaked.
- **Enable the auto-fix loop.** Only after the [ADR 0004](decisions/0004-auto-fix-loop.md)
  human checklist completes; it stays inert until then.
- **Security hardening.** Enable Snyk Code (SAST) once the org plan supports it.
- **E2E harness → nightly CI + Windows parity.** Wire the whole-repo e2e orchestrator into a
  nightly job and pin golden values for cross-platform determinism.

## 6. How agents use this document

- Read this before planning tasks; keep changes consistent with the §3 scope and §4
  invariants.
- Put concrete, changeable to-dos in [NEXT_STEPS.md](../NEXT_STEPS.md), not here.
- When a change would violate an invariant or expand scope, surface it for human decision
  rather than implementing it. The protected-path guard enforces this mechanically for
  evaluation-defining files; this section generalizes it as a standing principle.
- This charter is drift-checked: every file and ADR it links to is verified to exist by
  [scripts/check_charter_drift.py](../scripts/check_charter_drift.py).
