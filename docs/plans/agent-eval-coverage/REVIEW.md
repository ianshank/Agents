# Peer Review — Agent-Evaluation Coverage Analysis and Implementation Plan

**Reviewed artifacts:** two externally produced documents supplied 2026-08-05 —
(1) a "Coverage and Gap Analysis" grading this repository against a production-grade agent
evaluation model, and (2) a "Recommended approach" proposing five ordered OpenSpec changes.
**Method:** every falsifiable claim in both documents was re-checked against the working tree at
`b52c696` (merge of PR #118) and classified CONFIRMED / PARTIALLY TRUE / REFUTED with file:line
evidence. No claim was accepted on the strength of the source document alone.
**Outcome:** the corrected plan is `PLAN.md` in this directory; the five corrected change packages
are under `openspec/changes/`. Both source documents are superseded by those artifacts.

## Verdict

**Document 1** reaches the right headline conclusion — this repository has no trajectory
evaluation, no repeated-run reliability, and no environment-state validation — but roughly a third
of its coverage matrix is factually wrong, and its P1 priorities point at the repository's *most*
mature subsystems. It declares its own limitation: "I was not able to retrieve raw source bodies for
individual Python files through the available web tooling," and then grades capabilities "Not
Covered" on that basis. Absence of retrieval is not evidence of absence.

**Document 2** is substantially stronger. Its five-way decomposition and its delivery ordering are
correct and are carried forward unchanged. But it collides with four CI-enforced repository
invariants it never names, and several of its proposed code contracts do not match the actual types
— as written, three of its five changes would fail CI on first push.

## Part A — Findings against Document 1 (coverage analysis)

### A1 · Scope error: one package of six was audited — REFUTED as a repo-level assessment

`docs/CHARTER.md` §2 defines a monorepo of five Python packages plus vendored skills. The analysis
covers only `src/eval_harness`. Most of its "Not Covered" verdicts on calibration, human labelling
and the evaluation flywheel are wrong once the sibling packages are read.

### A2 · "Cohen's kappa / percent agreement — Not Covered" — REFUTED

`flow-corpus/flow_corpus/oracles/kappa_gate.py` implements a κ-gate that excludes indeterminate
pairs and power-gates via `is_directional_only`. `behavioral-regression/behavioral_regression/
oracle.py::validate_judge` measures judge verdicts against an aligned human-label set and returns a
`may_gate` trust signal consumed by the detector and the gate. Shipped as F-013 and F-016.

### A3 · "Human calibration workflow — Not Covered" — REFUTED

The analysis states the repository has "code governance, not human labeling of traces". F-034 ships
a human audit queue and verdict-dispatch surface: `merge-gate-audit.yml` (sampler → deduplicated
issue), `merge-gate-verdict.yml` (the only automated writer of the authoritative label, human-
triggered by construction), `scripts/record_audit_verdict.py`, `agent_core/audit_sampler.py`, and
`LabelSource.HUMAN_AUDIT` in `agent-core/agent_core/outcome_store.py`.

### A4 · "Calibrated judge decisions — mentioned only" — PARTIALLY TRUE, badly understated

F-043 ships `agent_core.calibration_report` with ECE, the Brier (Murphy) decomposition, AUROC and
abstention curves with Wilson CIs, keeping the human-audit-only PRIMARY view strictly separate from
the DIAGNOSTIC view. F-047 adds measured proxy correlation and a fail-closed PPI++ estimator.
`agent_core/golden.py` enforces held-out discipline in code (`evaluate_on_split` fits on the
calibration partition and evaluates on test only). The analysis graded this from a demo blurb.

### A5 · "Eval flywheel lacks a human review queue and production sampling" — PARTIALLY TRUE

The queue exists (F-034), passive labelling from CI signals exists (F-033), and durable persistence
across ephemeral runners exists (F-032, ADR 0018). What is genuinely absent is *agent task* traces
feeding that loop — a substantially narrower gap than described.

### A6 · It presents an already-recorded decision as an unnoticed gap — REFUTED

F-036 ("Real-transcript corpus bridge — flow_corpus ingestion from labeled store records") is marked
`deferred` in `features.yaml`. The repository identified this work and deliberately deferred it.

### A7 · Two recommendations conflict with stated invariants

Its proposed `calibration/labels.csv` plus a `judge_calibration` command would stand up a second
calibration system alongside F-016 and F-043. `openspec/project.md` additionally records that
**`agent_core` is config-file-free — calibration math takes no YAML knobs.**

### A8 · What Document 1 gets right — CONFIRMED independently

| Claim | Evidence |
|---|---|
| No trajectory representation or trajectory scorers | `grep -ril trajectory` matches only `flow-corpus/flow_corpus/specimens/react.py`, a synthetic *confidence* flow shape carrying no tool calls |
| No pass@k / pass^k / repeated-run evaluation | Zero matches repo-wide; `EvalEngine.run()` (`src/eval_harness/engine.py:269`) executes each item exactly once |
| No environment/state validation | All seven built-in scorers read `output.output` only (`src/eval_harness/scorers/__init__.py`) |
| No tool-selection, tool-argument or retrieval precision/recall scorers | Confirmed against the registered scorer set |
| No benchmark adapters (SWE-bench, τ-bench, BFCL, Terminal-Bench) | Confirmed |
| Judge *bias* probes absent | Confirmed — κ and power floors exist; order, verbosity and self-preference probes do not |

**Net:** the four P0 items (canonical trace schema, trajectory scorers, state validators, repeated-run
reliability) are correct and correctly ranked. P1 #6 (judge calibration workflow) and P1 #9 (online
production loop) should be substantially downgraded.

## Part B — Findings against Document 2 (implementation plan)

### B1 · Charter invariant collision, unacknowledged — BLOCKING

`docs/CHARTER.md` §4 invariant 1 states that components are added through registries and **"the
engine, core models, and registries themselves stay unmodified."** Change 1 adds a field to
`TargetOutput`, a core model; Change 2 rewrites `EvalEngine.run()`'s execution loop. §6 requires
surfacing such a conflict for human decision rather than implementing it unilaterally. Neither
document mentions the invariant. Resolved by [ADR 0031](../../decisions/0031-additive-core-model-extension-for-agent-evaluation.md).

### B2 · The `TargetOutput` contract in `design.md` is wrong and would be breaking — REFUTED

The actual type (`src/eval_harness/core/types.py:24-31`) is a **mutable** dataclass with field order
`output, latency_ms, error, metadata`. Document 2 proposes `@dataclass(frozen=True)` with order
`output, error, latency_ms, metadata, trajectory`. Freezing breaks every existing mutation site;
reordering breaks positional construction. `tests/test_backwards_compat_config.py` and
`tests/public_surface_baseline.json` exist to catch exactly this. Corrected form: append
`trajectory: AgentTrajectory | None = None` as the **last** field and leave mutability alone.

### B3 · The gate syntax it invents does not exist and would not parse — REFUTED

Document 2 proposes a top-level `gates:` block with `metric` / `minimum` / `maximum`. The
repository's model is `GateConfig.rules: list[GateRule]` with fields `score`,
`metric ∈ {mean, pass_rate}`, `min`, `max` (`src/eval_harness/config/models.py:156-171`). Charter §3
records: **"No permissive config parsing. `from_dict` is strict; unknown keys raise, no
fallbacks."** Corrected form: extend the `GateRule.metric` enum to
`{mean, pass_rate, pass_at_k, pass_power_k}` and keep `min`/`max`.

### B4 · `EvalContext` does not exist — REFUTED

Document 2's `StateAdapter` protocol is typed against `EvalContext`. The per-run context type is
`RunContext` (`src/eval_harness/core/types.py:110`). Related and more consequential:
`TargetRunner.run(self, item)` takes no context parameter (`core/interfaces.py:52-56`), so
"before/after capture in the runner" has no seam on the target. The **engine** must own snapshot
and reset.

### B5 · Architecture-airgap collision — BLOCKING for Change 4

`architecture.yaml` declares `behavioral_regression: [agent_core, flow_corpus]` and documents that
`eval_harness` must **never** depend on `flow_corpus` and vice versa — F-011's structural airgap,
enforced by `architecture-drift-guard` with F-012's forced-mismatch negative test. `architecture.yaml`
is itself a protected path, precisely because editing its declared edges could quietly dissolve the
airgap. Document 2 instructs Change 4 to "extend those mechanisms rather than create a second
calibration system", but the mechanisms sit on the far side of the airgap. Corrected: the shared
probe math lands in `agent_core` (dependency-free, already importable from both sides) and is
consumed by `eval_harness` through the existing declared edge
`agent_core_adapter: [agent_core, config, core]`. One calibration system, no manifest edit.

### B6 · The size-budget gate will hard-fail as tasked — CONFIRMED defect

`scripts/check_size_budget.py:45` sets `MAX_FILE_LINES = 500` as a hard failure.
`src/eval_harness/scorers/__init__.py` is already 316 lines; the seven scorers in Document 2's
tasks §3–4 push it well past the limit. Corrected: new scorers land in `scorers/trajectory.py`,
imported by `scorers/__init__.py` for registration only.

### B7 · Missing baseline tasks — every change would red-CI on first push

F-039 ships exact-equality surface guards with committed baselines:
`tests/public_surface_baseline.json` and `tests/plugin_registry_baseline.json`, enforced by
`tests/test_public_surface.py` and `tests/test_plugin_registry_surface.py`. Every newly exported
type and every newly registered scorer requires a regeneration
(`python tests/test_public_surface.py --update`) — under `tests/**`, a protected path. Document 2's
task lists never mention it.

### B8 · The architecture manifest is treated as conditional

Document 2 says "regenerate `architecture.mmd` **if** imports change". They will change, and
`architecture.yaml` is protected. This is a `[P]` task, not a conditional one.

### B9 · It over-claims what is reusable for judge calibration — PARTIALLY TRUE

`agent_core.golden.GoldenItem` is `(item_id, text, label ∈ {0,1}, domain, source)` — a binary-label
corpus for the merge gate, with no notion of an answer pair. Reusable: the deterministic
`seed:item_id` hash split and `evaluate_on_split`'s held-out discipline. Not reusable: the item
type. A pairwise, order-swapped calibration corpus is a new type.

### B10 · `not_applicable` invents a third verdict for no benefit

`ScoreResult` is `(name, value: float, passed: bool | None, comment, metadata)`, and the established
convention for a skipped scorer is `passed=None` with an explanatory comment — see
`AutoevalsScorer.score` (`src/eval_harness/scorers/__init__.py:301-308`). A new status enum would be
a further core-model change for no gain.

### B11 · Its verification commands are partly unrunnable

The `openspec` CLI is not installed in this environment, the `/opsx:*` slash commands are not among
this repository's skills (`skills/` provides `openspec-quality-plan` and `openspec-peer-review`),
and `openspec/project.md` states the directory is a coordination layer, **not** a source of truth.
The enforced entry points are `./scripts/quality-gate.sh [lint|typecheck|test|coverage|all]`,
`python scripts/validate.py --tier fast`, and `make check-all`.

### B12 · Review-artifact ordering is backwards versus house style

In this repository's own changes, `review.md` is the peer review that **motivates** the proposal —
`openspec/changes/archive/eval-proxy-and-estimator/proposal.md:4` reads "Motivated by: `./review.md`".
Document 2 §7 reads it last, as a closing checklist.

### B13 · Change 5 is a scope expansion, not merely a change

Charter §3 non-goals: **"This remains an evaluation harness, not a model trainer, an autonomous
merge bot, or a general observability platform."** A production trace-ingestion, redaction,
deduplication and review-queue pipeline requires a §3 Ratified Amendment and an ADR *before* the
proposal, exactly as the calibrated auto-merge gate did with ADR 0005. Document 2 correctly keeps
the pipeline offline and human-approved, but does not route it through the charter.

### B14 · A silent correctness trap in Change 2 that Document 2 never names — CONFIRMED defect

`_make_item_rng(base_seed, item_index)` (`src/eval_harness/engine.py:41`) seeds per item only. Run
k attempts without folding the attempt index into the seed and every deterministic target returns k
**identical** results — reporting a fabricated `pass^k = 1.0`, the precise failure the metric exists
to prevent. Two secondary hazards: `run()` checks for duplicate item IDs over the *dataset* list
(`engine.py:280-289`), so expanding attempts into that list before the check emits spurious
warnings; and `RunResult.to_dict()` emits `items` as a flat list carrying only `item.id`
(`types.py:86-106`), so k attempts serialise as indistinguishable entries unless attempt identity is
added to the payload.

### B15 · No per-change coverage acceptance

The root package floor is 96% (`pyproject.toml:162`); the sibling packages are at 95%. Five changes
of new subsystems must ship near-complete unit tests or the coverage gate goes red.

## What Document 2 gets right and is carried forward unchanged

- The five-way split into independently shippable capabilities, and the delivery order:
  measurement primitives → reliability → state → calibration → production loop.
- Trajectory capture stays target-owned; Langfuse is an export/observability sink, never the
  canonical trajectory representation.
- Normalise before matching; ignore volatile fields; **preserve duplicates**, because duplicates
  carry the precision and loop signal.
- `pass^k` aggregated per task, never pooled across unrelated tasks; every raw attempt persisted
  before aggregates are computed.
- Environment state reset or isolated between attempts; policy violations failing independently of
  goal success.
- Production ingestion stays offline, redacted and human-approved, and never runs in merge CI.
- Protected tasks marked `[P]`, with PRs split by protection level.

## Follow-on items surfaced, not fixed here

- **Document 1's benchmark-adapter recommendation (its P2 #11)** is unassessed by this review. It is
  plausibly a charter §3 scope question (SWE-bench-style adapters execute repository tests), and
  should get its own decision before any proposal.
- **`behavioral-regression` config validators lack an `isfinite` guard** — already recorded in
  `openspec/changes/archive/merge-gate-health-integrity/tasks.md`; unrelated to this review, noted so it is
  not lost.
