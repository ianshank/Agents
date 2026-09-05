# Peer Review — "Three OpenSpec Change Packages for Scenario Eval Matrices"

**Reviewed artifact:** an externally produced plan supplied 2026-09-05 proposing four OpenSpec
change packages (`add-testgen-eval-matrix`, `add-rca-eval-matrix`,
`add-requirements-gen-eval-matrix`, `add-judge-calibration-harness`) plus a three-model
agreement/disagreement synthesis and a 210-entry source list.

**Method:** every falsifiable claim about *this repository* was re-checked against the working tree
at `28eb09d` (merge of PR #180) and classified CONFIRMED / PARTIALLY TRUE / REFUTED with file:line
evidence. Every load-bearing external citation was independently re-fetched; a claim was not
accepted because its title sounded right. No claim was accepted on the strength of the source
document alone.

**Outcome:** the plan's *decomposition* is right and should be carried forward. Its *grounding in
this repository* is wrong in ways that would fail CI on first push, and one of its four changes
duplicates work already in flight. See §Verdict for the disposition.

---

## Verdict

The plan's structural thesis — "three new scorer families, three datasets, three targets, not a new
framework" — is correct and matches this repository's actual extension model (Charter §4 invariant
1). Carry it forward.

Everything downstream of that thesis was written against a *reading* of this repo rather than the
repo. Concretely:

- **Changes 2 and 3 are blocked on a CHARTER §6 Ratified Amendment.** Ingesting real incident
  telemetry and real shipped epics into a versioned corpus is the exact scope expansion that already
  put `openspec/changes/add-production-eval-flywheel/` into `Status: blocked` — "not … a general
  observability platform," CHARTER §3. The plan's critical path is not judge calibration; it is that
  amendment, or a re-scope onto synthetic corpora.
- **Change 4 duplicates an in-flight change.** `openspec/changes/extend-judge-calibration/` exists,
  is dated 2026-08-05, is partially implemented, and its proposal states as an explicit non-goal:
  "**a second calibration system.**" Change 4 is a second calibration system.
- **The plan's archive model is the opposite of this repo's.** It says deltas "merge into
  `openspec/specs/`". `openspec/README.md` and `docs/openspec-spike.md:36` both state
  `openspec/specs/` is **deliberately not populated**.
- **Two of the proposed scorers cannot be scorers.** `Scorer.score(item, output, ctx)` receives one
  output and cannot re-execute a target. `testgen_flake_rate` (5 re-runs) and `counterfactual_support`
  (replay with the cause removed, then restored) both require engine-level orchestration.
- **The matrix obligation is understated by roughly 30×.** 35 proposed scorers × the 5-dimension
  scorer floor = ~175 new matrix cells. Each change budgets this as one checkbox.
- **The named implementation files bust the size gate before they are written.**
  `MAX_FILE_LINES = 500`; the existing `scorers/trajectory.py` is 454 lines for *seven* scorers. The
  plan puts fourteen in one file.

On the citations: **11 confirmed as stated, 9 partially confirmed with corrections that change the
number or the scope, 3 misattributed, 1 refuted by measurement, 2 not found.** That is a better hit
rate than most strategy documents achieve. The problem is *where* the errors are — they cluster in
the claims the plan proposes to write into spec requirements:

- **`spec-driven-with-adr` does not exist** as an OpenSpec feature (C3.a), and ADRs placed in a
  change folder are swept into the archive rather than persisting (C3.b, verified by running it).
- **The κ sample-size thresholds are wrong by 4–6×** and are sourced to a Reddit thread (C4.e). The
  plan cites two other sources that contradict both it and each other.
- **Change 3's flagship ADR is refuted by measurement**: Drive DOCX export is not byte-stable, and
  `files.export` cannot target a revision at all, so `revision_id` + `content_sha256` pairs two
  things with no causal link (C3.d).
- **The "10% → 33% OpenRCA" progress claim does not survive** independent replication (12.5%), and a
  trivial `max-|Z|` heuristic scores 36.5% (C1.a).
- **The raw mutation-score definition is misattributed to Inozemtseva** (C2.d).

---

## Part A — Findings against this repository

Legend: **[C]** confirmed · **[P]** partially true · **[R]** refuted.

### A1 · Change 4 duplicates `extend-judge-calibration` — **[R]**

`openspec/changes/extend-judge-calibration/{proposal,design,tasks,review}.md` is an in-flight change
whose `## Why` section already refutes the "calibration is missing" premise:

> this repository already ships Cohen's κ with a statistical-power floor
> (`flow-corpus/flow_corpus/oracles/kappa_gate.py`), judge-versus-human validation returning a
> `may_gate` trust signal (`behavioral-regression/.../oracle.py::validate_judge`), held-out split
> discipline enforced in code (`agent_core/golden.py`), and a full calibration report with ECE, the
> Brier decomposition, AUROC and Wilson CIs (F-043).

The plan's Change 4 tasks map onto this one-for-one:

| Plan task | Already exists |
|---|---|
| 1.3 "Compute human-human kappa as the ceiling baseline" | `flow_corpus/oracles/kappa_gate.py` (κ + power floor) |
| 2.1 "compute judge-human kappa with CI" | `behavioral_regression/.../oracle.py::validate_judge` → `may_gate` |
| 2.3 "Freeze calibration_report artifact (ECE, Brier, AUROC, abstention, Wilson CIs)" | **F-043**, verbatim |
| 3.1 "Flip require_calibration_for_judge_gating on" | `src/eval_harness/gating/__init__.py:19`, already wired |

**Disposition:** delete Change 4. Fold the one genuinely new idea — a *sample-size and κ floor* on
the calibration artifact — into `extend-judge-calibration` as an additional spec delta. That change
is already the right home; it already owns the "Require a named calibration artifact ID before a
judge may gate" requirement.

### A2 · `require_calibration_for_judge_gating` is presence-only, so Change 4's scenario is a MODIFIED requirement filed as ADDED — **[R]**

`src/eval_harness/gating/__init__.py:19-41` checks exactly one thing:

```python
if targeted and config.judge_calibration is None:
    raise ValueError(...)
```

It never reads κ, N, or a confidence interval. The plan's scenario —

> GIVEN a calibration set smaller than 200 paired labels with measured kappa between 0.5 and 0.7 …
> WHEN `require_calibration_for_judge_gating` evaluates the artifact
> THEN gating SHALL be refused

— changes the behaviour of an existing, shipped function. In OpenSpec delta terms that is
`## MODIFIED Requirements`, not `## ADDED Requirements`. Filed as ADDED it either fails delta
validation or silently produces a duplicated requirement in the merged spec.

### A3 · The archive model is inverted — **[R]**

Plan: "On archive, each change's delta merges into `openspec/specs/eval-harness/spec.md`."

`openspec/README.md`:

> `openspec/specs/` is intentionally not populated (no duplicate registry).

`docs/openspec-spike.md:36`:

> `openspec/specs/` is deliberately **not** populated — capability state stays single-sourced

The actual compile-down, from `openspec/README.md` and `openspec/AGENTS.md`:

| OpenSpec artifact | This repo's enforced target |
|---|---|
| `proposal.md` + `tasks.md` | `docs/plans/<topic>/PLAN.md` |
| `design.md` | a numbered ADR at `docs/decisions/NNNN-*.md` |
| `specs/<cap>/spec.md` delta | `features.yaml` F-ID rows + `verification` bullets |
| each scenario | `scripts/validations/F_0NN.py` executable proof |
| `review.md` | the house `REVIEW.md` idiom |
| `openspec archive` | `status: done` + `implemented_in:<sha>` |

### A4 · The proposed change-folder layout is wrong in two ways — **[R]**

The plan proposes an `adr/` subfolder inside each change and omits `review.md`.

- **`review.md` is part of the documented layout** (`openspec/README.md` layout table) and is
  produced by two fleet roles — `spec-guardian` (conformance) and `peer-reviewer` (adversarial),
  per `openspec/AGENTS.md`. Every non-trivial in-flight change in the tree carries one. All four
  proposed packages omit it.
- **`adr/` is not a location this repo uses.** ADRs are immutable, numbered, and live at
  `docs/decisions/NNNN-*.md` (`openspec/project.md`). `design.md` *compiles down to* an ADR; it does
  not carry one inside the change folder. The plan's "ADRs persist outside the archived change" goal
  is already satisfied by the existing convention — it just puts the file in the wrong place.
- **Numbering collision.** The plan proposes `adr/0001-…`, `0002-…`, `0003-…`. `docs/decisions/`
  runs `0001`–`0041`; `0001` is `openai-compatible-judge.md`. The next free numbers are 0042–0044.

### A5 · Adding four change directories fails the OpenSpec change-index CI guard — **[C, unmentioned]**

`.github/workflows/docs.yml:139` runs an inline guard asserting that every directory under
`openspec/changes/` (excluding `archive/`) appears as a **link target** in `openspec/README.md`, and
that no archived one does. Substring mentions do not satisfy it — it matches `](target)` explicitly.

None of the four proposed `tasks.md` files updates `openspec/README.md`. All four changes fail
`docs.yml` on first push. One checkbox fixes it; it is missing from all four.

### A6 · Neither `report-only` gating nor a shadow mode exists in `eval_harness` — **[R]**

The plan's entire sequencing strategy rests on it:

> Run all three in `report-only` gating mode from the start; this matches the repo's existing
> shadow-mode pattern for the calibrated merge gate.

`GateRule` (`src/eval_harness/config/models.py:211-229`) requires `min`, `max`, or both, and
explicitly rejects a rule with neither because "Neither bound set means the rule can never fail
`evaluate_gate()` -- a silent no-op." `GateResult` is `passed: bool` + `failures: list[str]`. There
is no `report_only` field anywhere in `src/eval_harness/`.

The shadow-mode precedent the plan cites is real but lives elsewhere:
`.github/workflows/calibrated-merge-gate.yml:69-88` ("F-035 shadow mode (ADR 0005 soak, ADR 0018
persistence): a log-only …"). That is the **merge gate** in `agent-core`, not the eval harness.

**Disposition:** "report-only" is either (a) a fifth change adding `GateRule.report_only` to
`eval_harness.gating` — a protected path, so labelled and CODEOWNER-reviewed — or (b) an honest
restatement as "we simply won't add a gate rule yet", which is materially weaker because nothing
then computes and records the decision that *would* have been made. Pick (a). Sequence it first.

### A7 · The matrix obligation is understated by roughly 30× — **[R]**

ADR 0032 sets per-kind dimension floors. From the generated artifact
(`docs/matrix-coverage.md`): **`## scorer (floor: M1, M2, M3, M5, M6)`** — five mandatory
dimensions per registered scorer, each cell backed by at least one `test_m<dim>_*` method in
`tests/test_matrix_eval_tools.py`.

Scorers the plan proposes to register:

| Change | Count | Names |
|---|---:|---|
| 1 (testgen) | 14 | `testgen_mutation_score`, `testgen_coverage_delta`, `testgen_flake_rate`, `testgen_traceability`, `testgen_revision_rate`, `testgen_green_on_correct`, `requirement_obligation_recall`, `test_case_precision`, `boundary_partition_coverage`, `negative_path_coverage`, `unsupported_assumption`, `test_duplicate_rate`, `mutation_detection`, `test_executability` |
| 2 (RCA) | 13 | `rca_ac_at_k`, `rca_mrr`, `rca_avg_at_k`, `rca_component_match`, `rca_reason_match`, `rca_onset_within_tolerance`, `rca_triplet_all`, `rca_abstention_correctness`, `rca_false_accusation_rate`, `rca_timeline_completeness`, `rca_citation_grounding`, `rca_capa_actionability`, `counterfactual_support` |
| 3 (requirements) | 8 | `req_ac_recall`, `req_nfr_coverage`, `req_scope_hallucination`, `req_semantic_diversity`, `req_traceability_closure`, `req_iso29148_{unambiguity,verifiability,singularity}` |
| **Total** | **35** | |

The live scorer registry today holds **16** canonical entries. The plan more than triples it.
**35 × 5 = 175 new matrix cells**, i.e. ≥175 new test methods, plus:

- `tests/public_surface_baseline.json` regeneration — F-039 freezes `__all__` with **exact
  equality**, so an *addition* must be explicitly frozen too, not just a removal.
- `tests/plugin_registry_baseline.json` (M7 registry dimension is global-dynamic over the live
  registry + committed baseline).
- README registry sync of **both** `README.md` and `src/eval_harness/README.md`
  (`scripts/extract_registries.py:259` names both as default doc paths), gated by
  `scripts/check_readme_registries.py` → `extract_registries --check`.
- `docs/matrix-coverage.md` regeneration, freshness-gated by
  `tests/test_matrix_coverage.py::test_matrix_doc_is_fresh`.

Each change budgets all of this as: `- [ ] 3.1 Add MATRIX_KIND rows for all scorers`.

**And waivers are not an escape hatch.** ADR 0032 §3: "Floors are minimums, waivers are data. A dim
is floor for a kind iff it is meaningful for every member absent a documented waiver, and **waivers
stay a small minority**; … Waiver hygiene is self-guarded both ways (stale waiver fails; satisfied
waiver fails)." The `WAIVED` snapshot at acceptance holds **three** entries repo-wide. A change that
arrived with thirty waivers would fail the policy on its face.

**Disposition:** this is the single biggest sizing error in the plan. Either cut the scorer count
hard (see A12) or re-plan each change as 3–4 changes.

### A8 · The named implementation files exceed the hard size budget before they are written — **[R]**

`scripts/check_size_budget.py:46-48`:

```python
MAX_FILE_LINES = 500
MAX_FUNCTION_LINES = 50
MAX_PUBLIC_METHODS = 15
```

`MAX_FILE_LINES` is a **hard** gate (ADR 0019 — file-length gated, function/method limits warn).
Empirical rate from this repo: `src/eval_harness/scorers/trajectory.py` is **454 lines for 7
scorers** (~65 lines/scorer including docstrings the house style requires).

- Change 1: `src/eval_harness/scorers/test_generation.py`, 14 scorers ≈ **900 lines**. Fails.
- Change 2: 13 RCA scorers, one of which needs replay orchestration. Fails.
- Change 3: 8 scorers ≈ 520 lines. Fails, narrowly.

All three name a single module. All three need to be packages
(`scorers/test_generation/{mutation,coverage,traceability}.py`), which in turn interacts with
`architecture.yaml`'s component map (`scorers: [eval_harness.scorers]` — a subpackage is fine, but
the drift guard should be re-run).

### A9 · `testgen_flake_rate` and `counterfactual_support` cannot be scorers — **[R]**

`src/eval_harness/core/interfaces.py:39-49`:

```python
class Scorer(Protocol):
    """Scores a single (item, output) pair. ``name`` labels the emitted score."""
    def score(self, item: EvalItem, output: TargetOutput, ctx: RunContext) -> ScoreResult: ...
```

A scorer receives **one** output and has no handle on the target. It cannot re-run anything.

- **`testgen_flake_rate` (5 re-runs)** is not a new scorer; it is F-056's existing
  `run.repeat` + `ReliabilityAggregator` applied to an existing pass/fail scorer. Registering it as
  a scorer duplicates shipped machinery and costs 5 unnecessary matrix cells. Express it as
  `metric: pass_power_k` on `test_executability` instead.
- **`counterfactual_support`** ("replay the incident with the alleged cause removed then restored")
  requires re-executing a system under two counterfactual configurations. That is a **target**
  concern, and on *recorded* telemetry it is not obviously possible at all — see C-RCA-7.

### A10 · StateAdapters are snapshot/diff seams, not execution sandboxes — **[R]**

Plan: "Sandbox execution uses the existing `filesystem` and `sqlite` state adapters (F-060)."

`src/eval_harness/state_adapters/__init__.py:28-36` is explicit:

> the adapter does not intercept or observe the target's execution, only what it is told.

The `StateAdapter` protocol is `snapshot(ctx) -> StateSnapshot` plus `evaluate(...)`. It captures
world-state *around* `target.run(item)` so that a claimed side-effect can be verified. Running
generated pytest suites, seeding mutants, and measuring coverage is **target-side work**, and the
target must be a `callable` on `EVAL_HARNESS_CALLABLE_TARGET_ALLOWLIST` (ADR 0039) — which the plan
does get right.

The correction is small but load-bearing for the design doc: *execution happens in the target;
the state adapter verifies the residue.* As written, Change 1's design.md would send an implementer
down a dead end.

### A11 · The three corpora are placed in a package chartered to hold none of them — **[R]**

The plan writes datasets to `flow-corpus/test-generation/v1/`, `flow-corpus/rca/v1/`,
`flow-corpus/requirements/v1/`. Three problems, in ascending severity:

1. **Wrong path convention.** `flow-corpus/` is an installable Python package
   (`flow-corpus/pyproject.toml`); its data lives at `flow-corpus/data/suites/*.jsonl`.
2. **Wrong content charter.** `flow-corpus/README.md`:
   > It is **fully synthetic and firewalled from any live outcome data**, so a corpus run is
   > byte-reproducible.
   Replayed *real internal incidents*, *real shipped epics*, and *real focal methods* are live
   outcome data. This is the invariant the plan most directly contradicts.
3. **The airgap.** F-011 makes `flow_protocol` "the ONLY shared surface between the corpus and the
   harness"; F-012 adds a forced-mismatch negative test; `architecture.yaml` is itself a protected
   path so that this edge gets human review. `extend-judge-calibration` had to route its shared
   maths through `agent_core` under ADR 0031 *precisely because* the direct edge is illegal. The
   plan is unaware this constraint exists.

   To be precise about the enforcement boundary: `architecture-drift-guard` checks *import edges*
   via grimp, so a scorer reading a JSONL file by path would not trip it. The violation is of
   charter and of `flow-corpus`'s stated synthetic-only guarantee, not of the import gate. That
   makes it a review failure rather than a CI failure — which is worse, not better, because it
   lands silently.

**Disposition:** put the three corpora somewhere that is chartered for real data — a new top-level
`corpora/` or under `examples/` — and pin them with `flow_corpus.keying`/`pinning` idioms if
determinism is wanted. Do not extend `flow-corpus`.

Note also that `flow-corpus` already ships `mutation/engine.py` (inject known regressions) and
`holdout/{manager,rotation}.py` (deterministic keyed splits). Change 1 task 1.2 ("seed mutants") and
the recommendation's "keep a sequestered holdout set" both reinvent shipped modules without citing
them.

**A useful thing the plan missed, though.** `flow-corpus/data/suites/sdlc.jsonl` (200 rows) already
carries exactly the schema shape Change 2 needs:

```json
{"instance_id":"sdlc-0000","domain":"sdlc","difficulty":0.0,
 "solution_space":["cand_0_0","cand_0_1","cand_0_2","cand_0_3"],
 "correct":["cand_0_0"],"tool_available":true,"noise":0.0}
```

`solution_space` is the finite candidate set; `correct` is the confirmed answer. That is the
OpenRCA/RCAEval data model in miniature. **`rca_ac_at_k` and `rca_mrr` can be implemented and
matrix-covered against this synthetic suite before a single real incident is curated** — which
de-risks the longest-lead item in the whole plan (30–40 replayed incident bundles) and keeps the
scorer work inside the offline suite. The plan sequences the corpus first and the scorers second;
invert that for RCA.

### A12 · `req_semantic_diversity` breaks the offline invariant the plan itself asserts — **[R]**

Change 3 gates on "pairwise embedding distance / distinct-n". Change 1 task 4.1 asserts "Run offline
suite; confirm zero-network execution."

`pyproject.toml` keeps numpy/pandas deliberately out of the offline path — the comments are
explicit about it (`e2e-matrix`: "openpyxl pulls only et-xmlfile (no numpy/pandas), so it is safe";
`phoenix-evals`: "Split out because arize-phoenix-evals pulls pandas/numpy"; `autoevals`:
"Lightweight … no numpy/pandas … so — unlike braintrust — this extra IS installed in the offline
test job"). An embedding-distance scorer needs either a network embedding call or a bundled local
model plus numpy. Both break the property.

**Disposition:** ship `distinct-n` / type-token ratio / n-gram Jaccard as the offline default —
pure-Python, deterministic, no new dependency — and put embedding-distance behind an optional extra
that degrades to a no-op when absent, mirroring the `phoenix`/`braintrust` seam pattern this repo
already uses for exactly this reason.

### A13 · Numeric literals in requirements violate a stated convention — **[R]**

`openspec/project.md`, "Conventions this layer must respect":

> **No numeric literals at call sites** — tunables live on frozen `*Config` dataclass fields.

The plan bakes into *requirement text*: k=5, ±60s, 200 paired labels, 400 paired labels, κ bands
0.5–0.7 and 0.3–0.4, TPR/TNR >90%. Change 4's ADDED-requirement scenario is a numeric literal
embedded in a spec. These must be `*Config` fields with the numbers stated in `design.md` and
justified there — otherwise the thresholds are unreviewable and, worse, unchangeable without a spec
amendment.

The plan does get one convention right: `scripts/validations/F_0NN.py` as a placeholder respects
"**F-numbers are claimed at land, never reserved** in a proposal."

### A14 · Protected-path load is real and unbudgeted — **[C, understated]**

`scripts/eval_protected_paths.py:22-35` confirms the plan's governance claim exactly:
`features.yaml`, `config/**`, `src/eval_harness/{gating,scorers,judges}/**`,
`scripts/validations/**`, `.github/**`, root `tests/**`.

The plan presents this as the VP slide's strongest asset. It is — and it is also a schedule risk it
never prices. **Every task in all four changes touches at least one protected path**: scorers
(protected), matrix tests under root `tests/**` (protected), `features.yaml` (protected), validation
scripts (protected), `docs.yml` (protected). Every push in a "three-sprint plan" needs the
`eval-change-approved` label plus CODEOWNER review, under ADR 0037's single-maintainer branch
protection. Three sprints is not a schedule; it is a hope.

### A15 · Feature-ID attributions — mostly **[C]**, one **[P]**

Checked against `features.yaml`:

| Cited | Actual name | Verdict |
|---|---|---|
| F-006 regression gate | "Regression gate (net-new failures vs HEAD)" | **[C]** |
| F-007 protected-path guard | "Eval-integrity protected-path guard" | **[C]** |
| F-039 surface freeze | "Public-surface backwards-compat guard…" | **[C]** |
| F-049 bin-CI-width fail-open | "Merge-gate calibrator-health integrity…" | **[C]** |
| F-051 trajectory scorers | "Agent trajectory evaluation (… seven trajectory scorers)" | **[C]** |
| F-053 matrix completeness | "Matrix completeness: derived component census…" | **[C]** |
| F-056 `ReliabilityAggregator` / `pass_power_k` | "Repeated-attempt reliability metrics (pass@k / pass^k)" | **[C]** |
| F-059 panel judge quorum abstention | "PanelJudge: aggregate N member judges, abstain rather than guess" | **[C]** |
| F-060 state adapters | "Stateful outcome evaluation: StateAdapter seam…" | **[C]** |
| **F-057 = `require_calibration_for_judge_gating`** | **"Judge bias calibration (order, verbosity, self-preference)"** | **[P]** |

F-057's *validation script* does assert `require_calibration_for_judge_gating`, so the pointer is
defensible — but the plan describes F-057 as if calibration-gating were its subject. It is not; bias
probes are. The distinction matters because the plan then proposes to "flip F-057 on", which is not
a thing F-057 does.

Also **[C]**: `ADR 0032` is `matrix-completeness-policy.md`; `EVAL_HARNESS_CALLABLE_TARGET_ALLOWLIST`
is real and deny-by-default (ADR 0039); `html_file` sink, `mock_http` adapter, `state_transition`
scorer, `BudgetLedger`, and `agent_core.calibration_report` all exist as claimed;
`demo/run_demo.sh` is a one-command `--offline` demo.

### A16 · Change 2 is blocked on a CHARTER §6 Ratified Amendment it never mentions — **[R]**

This is the finding that most changes the plan's delivery order, and it was already decided in this
repo three weeks before the plan was written.

`openspec/changes/add-production-eval-flywheel/proposal.md` carries **`Status: blocked`**, and says
why:

> CHARTER §3 states: *"This remains an evaluation harness, not a model trainer, an autonomous merge
> bot, or a general observability platform."* A production trace-ingestion, redaction, deduplication
> and review-queue pipeline is a scope expansion, not merely a new capability. Under CHARTER §6 it
> needs a Ratified Amendment and its own ADR **before** this proposal is accepted — the same route
> the calibrated auto-merge gate took through ADR 0005.
>
> ADR 0031 authorises additive core-model and engine changes for agent evaluation. It does **not**
> authorise this. Do not begin implementation on the strength of it.

Now read Change 2's scope: 30–40 replayed internal incident bundles of logs, metrics, traces and
deploy events; a `mock_http` adapter simulating telemetry APIs; `rca_timeline_completeness`;
`rca_citation_grounding` ("every claim linked to a real telemetry artifact"); `rca_capa_actionability`.
By CHARTER §3's own words that is a general observability platform, built on ingested production
traces.

Change 3 is in the same position for a different reason: 20–30 *real shipped epics* with real Google
Drive and Context7 provenance is production data ingestion into a versioned corpus, which is exactly
what `add-production-eval-flywheel` was blocked for.

**Disposition:** Changes 2 and 3 cannot be "proposed and drafted in parallel" as the plan's
sequencing diagram claims. Either (a) both wait behind the same CHARTER §6 amendment — and then that
amendment, not judge calibration, is the real critical-path item; or (b) both are re-scoped onto
synthetic or fully-redacted corpora, which keeps them inside ADR 0031's existing authority. Option
(b) is the faster path and is compatible with §A11's re-homing recommendation and with the
`sdlc.jsonl` prototype route below. The plan's dependency graph has the wrong root node.

### A17 · Sequencing collision with `prove-m8-execution` — **[R]**

`openspec/changes/prove-m8-execution/proposal.md` (dated 2026-09-02, three days before this plan)
establishes that the M8 Composability dimension is currently **vacuous**: `pipeline_kinds()` credits
a component "the instant its name appears in a config that passes Pydantic validation — never once
its actual protocol method … is observed to run." The change replaces config-presence credit with an
execution ledger.

Landing 35 new scorers *before* `prove-m8-execution` mints 35 new provably-vacuous M8 cells in
`docs/matrix-coverage.md` — precisely the evidence-integrity defect that change exists to remove,
and precisely the kind of thing that discredits the VP claim "these metrics cannot be quietly
weakened." Landing *after* means all 35 need real execution proofs, which raises the per-scorer
cost again on top of §A7.

**Disposition:** `prove-m8-execution` lands first. State that dependency explicitly.

### A18 · The VP framing was already reviewed and rejected once — **[P]**

`openspec/changes/add-measurement-harness-wedge/proposal.md` records that its predecessor,
`add-business-readiness-wedge`, was found **undeliverable** by peer review "on this repo's own
documented terms," because the only shipped confidence signal is a diff-shape heuristic whose
honest expected discrimination (ADR 0023 §1: AUROC ≈ 0.5–0.65) sits below the gate's own health
floor (`min_auroc = 0.65`), and because the live outcome store holds **zero** `HUMAN_AUDIT` labels
across 46 records.

The plan's "Archive and VP Deliverable" section proposes generating the VP artifact from the merged
`html_file` sink plus `docs/matrix-coverage.md`. That is a better-grounded artifact than the
rejected wedge — matrix coverage is real, generated, and freshness-gated. But the plan's Sprint-3
recommendation to "emit ECE/Brier/AUROC/abstention with Wilson CIs from
`agent_core.calibration_report`" walks straight back into the rejected framing: **with zero
`HUMAN_AUDIT` labels in the store, that report has nothing to compute over.** Read
`add-measurement-harness-wedge/review.md` before building any slide on those four numbers.

### A19 · What the plan gets right, and should keep

Not everything here is a defect. These are correct and worth stating so they survive the rewrite:

- The registry-extension thesis, and the refusal to build a new framework.
- The oracle hierarchy (schema → parse → execute → mutate → deterministic trace → calibrated judge
  → human), and the rule that nothing above the execution line may be judge-backed.
- Abstention as a first-class metric with negative-control rows. This matches F-059's design intent.
- Gating on `pass_power_k` rather than `pass_at_k` — correct, and F-056 already supports it as a
  `GateRule.metric` value.
- Deterministic component/onset fields, judge only on free-text `reason` and CAPA.
- Keeping a sequestered holdout so scorer iteration cannot overfit the presentation corpus.
- Content-hashing retrieved evidence rather than trusting a source's own revision identifiers
  (subject to the export-determinism caveat in C-TOOL-8).
- Naming proxy-metric validity, contamination, and judge self-gaming on the slide rather than
  waiting to be asked.

---

## Part B — Findings against the three-model synthesis

### B1 · "Where Models Agree" is a consensus table, not evidence — **[P]**

Three models agreeing is three samples from heavily overlapping training distributions. The
agreement rows are *hypotheses with a prior*, not findings. Two of them are load-bearing and
unverified: "judges must be calibrated before gating" (correct, and already this repo's policy) is
fine; "VP deck must lead with business KPIs" is sourced entirely to two marketing blog posts
([7],[8]) and should not be presented with the same weight as the mutation-testing literature.

### B2 · The RCA schema disagreement is resolved in the wrong direction — **[P]**

The synthesis says "use the triplet schema for your data model and AC@k for scoring, and add
counterfactual replay as the gold-tier oracle." The first half is right. The second half is
unimplementable on the corpus the plan specifies — replayed incident *bundles* (logs/metrics/traces
as recorded artifacts) support no counterfactual. See C-RCA-7. Ship the triplet + AC@k; drop
counterfactual replay from scope, or change the corpus from recorded bundles to a re-runnable
fault-injection harness, which is a different and much larger project.

### B3 · The calibration-set sizing disagreement is resolved by citing a Reddit thread — **[R]**

"200 paired labels minimum (400 if κ<0.4)" is sourced to `reddit.com/r/LangChain/...` ([17]) and
then written into a spec requirement. See C-JUDGE-7 for what the actual sample-size literature says.
Regardless of whether the number survives, a spec threshold sourced to a Reddit post will not
survive the first technically sharp reviewer, and this plan is explicitly built to be shown to one.

---

## Part C — Citation verification

Every load-bearing citation was independently re-fetched. Sources that could not be reached are
marked **NOT REACHED** with what was tried, rather than assumed good.

### C1 · Root-cause analysis

| # | Claim | Verdict |
|---|---|---|
| C1.1 | OpenRCA = 335 real failure cases | **CONFIRMED** (Telecom 51 + Bank 136 + Market 148) |
| C1.2 | 68 GB telemetry | **CONFIRMED** ("over 68 GB"; 68.5 GB / 523M lines) |
| C1.3 | Triplet = onset datetime + component + reason, from finite sets | **CONFIRMED** (73 components, 28 reasons, enumerated in-prompt) |
| C1.4 | Tolerance = ±1 minute | **CONFIRMED** in harness source |
| C1.5 | "OpenRCA agents went ~10% → ~33%, 2025→2026" | **UNSUPPORTED** — see C1.a |
| C1.6 | Reddit r/sre "1 in 3 real root-cause cases" | **SOURCE NOT FOUND** |
| C1.7 | Traversal: "bounded telemetry reasoning, not production RCA" | **CONFIRMED**, severe COI — see C1.c |
| C1.8 | RCAEval = 735 failure cases | **CONFIRMED** (RE1 375 + RE2 270 + RE3 90) |
| C1.9 | RCAEval = 11 fault types | **CONFIRMED** (4 resource + 2 network + 5 code-level) |
| C1.10 | RCAEval defines AC@k, Avg@k **and MRR** | **MISATTRIBUTED** — MRR is not in the paper |
| C1.11 | 30–70% MTTR / 40–60% MTTD / 60–90% alerts / 45min→5min | **UNSUPPORTED** — vendor marketing; one cited URL does not resolve |
| C1.12 | arXiv 2403.04123 as a methodological prior | exists, but **misleading as a prior** — see C1.d |
| C1.13 | Counterfactual replay as "the strongest oracle available" | **PARTIALLY SUPPORTED / MISFRAMED** — see C1.e |

#### C1.a · The "~10% → ~33%" progress claim is the weakest number in the plan

This matters because the plan proposes to put it on a VP slide as the honest expectation ceiling —
i.e. it is load-bearing for the credibility argument, not decoration.

- **The 2025 anchor is roughly right.** OpenRCA's best reported baseline is **11.34%** (Claude 3.5 +
  RCA-agent), corroborated at 11.3% strict / 17.3% partial.
- **The 2026 anchor does not survive.** The strongest *independent* replication ran the full 335-case
  benchmark across 5 models — 1,675 agent runs, 609.9 GPU-hours — and tops out at **12.5% strict /
  22.4% partial** (Gemini 2.5 Pro). Claude Sonnet 4 scores 3.9% strict in the same run. A separate
  July-2026 paper reaches 25.71 on *one sub-dataset* (Market CB1) with GPT-5.2 plus a hand-built
  multi-agent pipeline and injected domain knowledge.
- The only ~33–35% figure traceable anywhere is **34.9%, from a model vendor's own launch
  materials**, with unstated scaffold, subset and scoring mode. The primary was egress-blocked in
  this session (**NOT REACHED**); it was visible only through third-party summaries.

  So: 11.3% → 12.5% on independent evidence, not 11% → 33%.

- **Worse, there is a scoring-mode trap the claim walks straight into.** OpenRCA's released
  `evaluate.py` scores each triplet element *independently* and `report()` prints **both** a
  `Strict Accuracy` and a `Partial Accuracy`, the latter running ~1.5–2× the former. Any
  "10% → 33%" comparison that does not state strict-vs-partial at both ends is invalid on its face.
  Two further details the "triplet" framing hides: a case may carry **two** root causes (the harness
  permutation-matches them), and all timestamps are **UTC+8** — timezone drift is the benchmark's
  own documented leading cause of spurious mismatches, and is independently measured as a 23.3%
  "Timestamp Error" pitfall rate. **Change 2's `rca_onset_within_tolerance` must pin the timezone
  explicitly or it will silently score noise.**

- **And a trivial heuristic beats the claimed number.** An audit over 778 matched scoring units from
  OpenRCA + RCAEval + PetShop reports pooled top-1 accuracy of **0.365 for an untuned
  `max-|Z|` predictor** ("pick the metric with the biggest z-score, map it to a service") against
  **0.246 for BARO**, a published RCA method. No tuning, no training split. Any "agents now solve
  ~1 in 3" claim must first explain why that beats argmax-of-z-score. The same audit finds all six
  method pairs reverse sign across subsystems and every random-effects prediction interval crosses
  zero — pooled leaderboard numbers do not license subsystem-level claims.

  **This is a gift to the plan, not just a correction.** `max-|Z|` is a five-line, deterministic,
  offline scorer. It is the honest baseline row for the VP deck and the natural first RCA scorer to
  implement — before any agent is evaluated at all.

**Correction to write:** "Best reported OpenRCA baseline is 11.34% (Claude 3.5 + RCA-agent,
ICLR '25); the strongest independent 2026 full-benchmark replication reports 12.5% strict / 22.4%
partial. A 34.9% figure appears in vendor materials and has not been independently reproduced. A
trivial `max-|Z|` heuristic scores 36.5% pooled — treat any single headline solve-rate with
suspicion."

#### C1.b · RCAEval does not define MRR

Section 4.2, verbatim: *"We currently support two standard metrics: AC@k and Avg@k to measure the
RCA performance."* `Avg@k = (1/k) Σ AC@j`. There is no MRR, no reciprocal rank. The plan lists
`rca_mrr` in Change 2's design and attributes the metric set to RCAEval in the disagreement table.
Drop `rca_mrr`, or cite whatever actually defines it.

Two more things a sharp reviewer will catch: RCAEval is a **4-page WWW '25 Companion short paper**,
not a full paper, and its preliminary experiments cover one system (Train Ticket) of one dataset
(RE2) with 8 of 15 baselines. It also contains **no LLM evaluation at all**. As a data source it is
fine; as the methodological precedent for an LLM-agent eval harness it is the wrong citation.

#### C1.c · Traversal: right argument, wrong kind of source

The blog exists; its actual title is *"OpenRCA Is Not Root Cause Analysis: What Is Missing"* (the
plan's "why that matters" appears only in the URL slug). The quoted framing checks out —
scores are *"signals of bounded telemetry reasoning, not proxies for production root cause
analysis."* Its falsifiable example is good: MySQL02 memory sits at ~98% before, during *and* after
the injection, so the labelled fault is not recoverable from the released telemetry.

Traversal is a commercial autonomous-RCA vendor that ships a competing benchmark. Cite it as vendor
commentary whose technical point is **separately corroborated** by three non-vendor papers, and cite
those instead where possible.

#### C1.d · arXiv 2403.04123 is a weak prior for a telemetry-grounded harness

Roy et al. (WSU + Microsoft), FSE 2024 Companion. It evaluates ReAct on 500 incidents sampled from a
proprietary Microsoft portal using **title + description only — no metrics, logs, or traces** —
scored with C-BLEU / S-BLEU / rougeL / METEOR / BERTScore. Best rougeL is 20.30 (a *retrieval*
baseline); ReAct gets 17.45, i.e. it loses on every automatic metric. The paper itself says those
metrics "are not able to accurately measure factual accuracy."

Its future-work section is the part worth citing: it calls for *"construction of a simulated RCA
environment"* to escape *"the limitations of performing RCA on a static dataset."* That is the
strongest existing support for the plan's counterfactual instinct — and also the clearest statement
of why the plan's own corpus design defeats it.

#### C1.e · Counterfactual replay: not novel, and not feasible on the corpus the plan specifies

The plan presents this as GPT-5.6's unique discovery and "the strongest possible RCA oracle." Both
halves need correcting.

**It is not novel.** Directly citable prior art:
- **AID** — Fariha, Nath & Meliou, *Causality-Guided Adaptive Interventional Debugging*, SIGMOD 2020
  (arXiv 2003.09539): statistical debugging + causal analysis + **fault injection** + group testing,
  executing "a sequence of interventions on the predicates to discover their true causal
  relationships." The remove→observe loop, formalized, in 2020.
- **Sage** — Gan et al. (Cornell/Google), ASPLOS 2021 (arXiv 2101.00267): states the exact SRE
  practice — *"SREs can verify if a suspected root cause is correct by reverting a microservice's
  configuration to a state known to be safe… If the problem is resolved, the suspected culprit is
  causally related."*
- Also CRFD (TOSEM 2025), ICECREAM (2307.09779), NetCause (2606.13543), *Probability of Root Cause*
  (2605.11776), *Counterfactual-Based RCA for Dynamical Systems* (ECML 2024).

The genuinely under-cited half is the **A-B-A restore-and-confirm-return** step — the software
analogue of Koch's postulates. The reasoning pattern is discussed in the literature; no software-RCA
paper appears to formalize it as a named validation protocol. If the plan wants a novelty claim,
that is the one it can actually defend.

**It is not feasible as scoped.** Recorded telemetry is an immutable snapshot; there is no world to
replay in which the cause was absent. Sage is explicit about the workaround and its cost: it
*"leverages historical tracing data to generate realistic counterfactuals"* via a Causal Bayesian
Network plus one CVAE per microservice, *"replacing a microservice's metrics with their respective
normal values."* That is **model-based counterfactual estimation, not replay**, and it needs a
correct dependency graph, causal sufficiency, stationarity, and enough samples to fit.

Those assumptions are measurably violated on exactly this data: Granger, PC, FCI, LiNGAM and NTLR
all score **0.00 at both Acc@1 and Acc@10** on OpenRCA Market CB1, because ~30 timestamps per window
are being fitted against 640–2500 metric columns. A counterfactual validator on recorded telemetry
would rest on causal machinery that scores zero on that telemetry.

**The correct substitute already exists.** OpenRCA 2.0 (arXiv 2606.27154) calls it **PAVE**: don't
replay — use the **fault-injection record** `do(v_root)`. *"Knowing the intervention turns an
ill-posed inverse problem into a well-posed forward verification task."* Cite that, drop
`counterfactual_support` from Change 2, and note that §A9 independently shows it cannot be a
`Scorer` anyway.

#### C1.f · MTTR: the one serious study argues against the plan's framing

No peer-reviewed or independently-audited source exists for the 30–70% / 40–60% / 60–90% ranges.
IrisAgent's page does say "40–70% MTTR reduction within 6–18 months" and "up to 90% fewer alerts,"
with no study, sample, baseline definition, or citation. **The `struct.ai/articles/...` URL in the
plan's source list does not resolve** — the "45 min → 5 min" line lives on a different
`blog.struct.ai` marketing page. Fix or drop it. MTTR is not comparably defined across
organizations, so "up to X%" ranges are not poolable even in principle.

There *is* one methodologically serious MTTR study — Meta's **DrP** (arXiv 2512.04250): a full year,
thousands of incidents, a control group of non-DrP teams, committee-reviewed timestamps, a real
threats-to-validity section, and **20% average MTTR improvement** (50–80% for teams with 10+
analyzers). Three caveats: first-party, preprint, and — decisively — **DrP is not AI.** It is coded
investigation playbooks. The paper's own lesson heading reads *"Do not over-index on AI based
systems for diagnosis."*

If the VP deck needs an MTTR anchor, that is the honest one, and it reframes the pitch: the
defensible claim is *"structured, deterministic diagnosis automation moves MTTR ~20% in a measured
setting; we are evaluating whether agents can extend that,"* not *"industry claims 30–70%."*

#### C1.g' · A better headline finding than any solve-rate delta

The same 1,675-run replication publishes a failure taxonomy: **Hallucination in Interpretation
71.2%** and **Incomplete Exploration 63.9%**, both above 66% / 53% for *every* model regardless of
capability tier. Prompt engineering did not move it; enriching the inter-agent protocol cut
communication pitfalls by up to 15pp and cut execution time 22.3%.

That says the bottleneck is the agent framework, not the model — which is a far stronger argument
for building this eval harness than any percentage the plan currently cites, and it directly
motivates `rca_abstention_correctness` and `rca_false_accusation_rate` as the two headline scorers.

### C2 · Test generation

| # | Claim | Verdict |
|---|---|---|
| C2.1 | arXiv 2607.18057, agentic-PR coverage: 35.9% Java / 22.5% Python | **CONFIRMED**, denominators overstated — see C2.a |
| C2.2 | arXiv 2607.22880 questions coverage/mutation as fault-detection proxies | **PARTIALLY CONFIRMED** — conclusion inverted, see C2.b |
| C2.3 | MuTAP reached 93.57% mutation score, beating Pynguin and few-shot | **CONFIRMED** (best-of-four config, synthetic benchmark) |
| C2.4 | TESTEVAL benchmarks coverage regimes | **CONFIRMED** (overall / targeted line+branch / targeted path) |
| C2.5 | TestBench evaluates class-level context regimes | **CONFIRMED** (self-contained / full / simple) |
| C2.6 | GBCV stratifies corpora by control-flow and variable-usage composition | **PARTIALLY CONFIRMED** — it *synthesizes*, see C2.c |
| C2.7 | Raw + normalized mutation score "per Inozemtseva's definitions" | **MISATTRIBUTED** — see C2.d |
| C2.8 | arXiv 2502.08943 supports multi-generation estimation | **CONFIRMED**, cited title is stale |
| C2.9 | `pass^k` origin and definition | **CONFIRMED**, name misread — see C2.e |

No fabricated arXiv identifiers were found. Both `2607.*` IDs are legitimate July 2026 preprints and
resolve. All nine identifiers exist.

#### C2.a · The agentic-PR percentages are right; the denominators are not

Verbatim: *"only 35.9% of Java (23/64) and 22.5% of Python (136/605) Code + Tests PRs actually show
any improvement."* Both numbers exact.

But the plan writes "35.9% of Java and 22.5% of Python PRs." The denominators are **64 Java and 605
Python `Code + Tests` PRs that could be built and instrumented** — from a starting population of 532
Java / 4350 Python PRs. Stated as "of Java PRs," the claim overstates its scope by roughly an order
of magnitude on the denominator, and that is exactly the kind of thing a technically sharp VP checks.
Write "of instrumented code-plus-tests PRs."

#### C2.b · The replication study is cited for half of what it found

arXiv 2607.22880 is Zhao, Zhou & Cohen, *Proc. ACM Softw. Eng.* 3 (ISSTA 2026), DOI 10.1145/3832093.
Its real title is *"Do Coverage and Mutation Scores of LLM-Generated Test Suites **Correlate with
Their Effectiveness? (Replicability Study)**"* — the plan's bracketed paraphrase is not the title.

The raw+normalized recommendation is genuinely supported (§3.6). The characterization is not. The
paper's abstract says *"Our findings diverge substantially from prior results"*: in regression-style
settings with **bug-free** code under test, coverage and mutation **are** informative for
cross-model comparison even with suite size controlled (inter-model branch coverage vs. bug
detection **r = 0.861**). They lose predictive power only when the code under test is already buggy.

Citing it as generic support for "proxies are gameable" inverts half its contribution — and the
half it inverts is the half that *supports* the plan's own mutation-score-as-L1-metric decision. The
plan is arguing against its own best evidence.

#### C2.c · GBCV synthesizes a corpus; it does not stratify one

The acronym is exact: *"Generated Benchmark from Control-Flow Structure and Variable Usage
Composition."* But the method builds **786 Python programs from CFG templates** with p-use/c-use
placeholders — *"The dataset we used is not extracted from any existing repository."*

The plan cites it as "principled stratification for your internal focal-method corpus." It does
report across 7 control-flow categories, so *stratified reporting* is fair; *stratifying an existing
corpus* is not what it does. The distinction matters for Change 1 task 1.1 ("curate 60–100 focal
methods stratified by control-flow/variable-usage complexity") — GBCV gives you a **generator**, not
a stratification scheme, and a generator is arguably better for this repo because it produces
synthetic data, which sidesteps §A16's charter problem entirely.

#### C2.d · The raw mutation-score definition is misattributed — the most serious citation error in the plan

The plan's spec delta says a scorer *"SHALL report both raw mutation score (killed / all mutants
generated for the focal method) and normalized mutation score (killed / mutants covered by the
suite), **per Inozemtseva's definitions**."* That sentence is written into a `## ADDED Requirements`
block, so the misattribution would land in the merged spec.

- **Normalized: correctly attributed.** Inozemtseva & Holmes (ICSE 2014, DOI 10.1145/2568225.2568271,
  ICSE 2024 Most Influential Paper) define a *normalized effectiveness measurement* = mutants killed
  ÷ **non-equivalent mutants covered by the suite**. Note the original's term is "normalized
  effectiveness measurement" — "normalized mutation score" is downstream usage.
- **Raw: wrongly attributed.** Inozemtseva's non-normalized denominator is **all non-equivalent
  mutants generated for the entire subject project**, not for the focal method. The focal-method
  denominator is Zhao et al.'s own 2026 adaptation, and they flag it explicitly: *"Inozemtseva et al.
  define raw mutation score as killed mutants divided by all mutants generated for the entire subject
  project, a ratio we instead compute over the mutants generated for the focal method associated with
  each test suite; their normalized mutation score … is adopted unchanged."*
- The plan also drops **"non-equivalent"** from both denominators. Inozemtseva excludes equivalent
  mutants; a scorer that does not will systematically under-report.

**Fix:** cite Zhao, Zhou & Cohen (ISSTA 2026) for the focal-method raw score, Inozemtseva & Holmes
for the normalized one, and restore "non-equivalent" to both.

**Caveat on this finding.** The primary Inozemtseva PDF was egress-blocked in this session
(**NOT REACHED** — arxiv.org, cs.ubc.ca, dl.acm.org, semanticscholar, uwspace.uwaterloo.ca all
blocked). The attribution above is triangulated from the ISSTA 2026 replication study's verbatim
restatement plus two independent full-text searches that agreed. Confirm against §III/§IV of the
original before this goes in front of anyone external.

#### C2.e · `pass^k` is "pass hat k," and the MuTAP number needs a qualifier

- **Origin confirmed:** τ-bench, Yao, Shinn, Razavi & Narasimhan (Sierra), arXiv 2406.12045, Jun
  2024: *"we propose a new metric – **pass^k (pass hat k)**, defined as the chance that all k i.i.d.
  task trials are successful, averaged across tasks."* Unbiased estimator
  `pass^k = E_task[C(c,k)/C(n,k)]`. `pass^1 = pass@1`. Reported: gpt-4o pass^1 ≈ 61.2 on τ-retail but
  **pass^8 < 25%** — which is the single best illustration of why the plan is right to gate on pass^k.
  `pass@k` is Chen et al. 2021 (Codex/HumanEval), not τ-bench.
- The repo's own naming (`pass_power_k`, F-056) is therefore a house convention, not the literature's
  name. Worth one line in `design.md` so a reader doesn't go looking for "pass-power-k."
- **MuTAP's 93.57%** is the best of four configurations (zero-shot Codex 89.13%, zero-shot Llama-2
  91.98%, few-shot Codex 92.02%) on the **HumanEval synthetic-mutant** benchmark. On the real-bug
  Refactory benchmark the figure is 94.91% vs Pynguin 67.54%. Don't conflate them.
- **arXiv 2502.08943**'s cited title is the v1 title; the published Findings of ACL 2026 title is
  *"Beyond the Singular: Revealing the Value of Multiple Generations in Benchmark Evaluation."* Its
  evidence is strong (Δ at k=1 reaches **18.6 points** on GSM8K; single-generation ranking flips
  between two models 20% of the time on GPQA) but it studies LLM benchmark scores generally, not test
  suites — cite it methodologically, don't imply it studied test generation.

### C3 · OpenSpec and external tooling

These were verified by installing the OpenSpec CLI (`Fission-AI/OpenSpec` @ v1.12.0) and running the
workflow, and by live Google Drive export tests — not by reading documentation.

| # | Claim | Verdict |
|---|---|---|
| C3.1 | Four artifacts per change; `design.md` always produced | **PARTIALLY CONFIRMED** — `design.md` is conditional |
| C3.2 | Delta headers are ADDED / MODIFIED / REMOVED | **PARTIALLY CONFIRMED** — there are **four**; `RENAMED` is missing |
| C3.3 | Archive merges deltas; proposal/design/tasks move to `archive/<date>-<id>/` | **PARTIALLY CONFIRMED** — the *whole* folder moves |
| C3.4 | A `spec-driven-with-adr` schema exists | **NOT FOUND — it does not exist** |
| C3.5 | `openspec/schemas/spec-driven/schema.yaml` layout | **PARTIALLY CONFIRMED** — that path is for a fork/override only |
| C3.6 | Dependency ordering (proposal → specs; design ∥ specs; tasks ← both) | **CONFIRMED exactly** |
| C3.7 | ADRs in `adr/` "persist outside the archived change" | **REFUTED** — live test, they are swept into the archive |
| C3.8 | Context7 two-step returns version-specific, hashable docs | **PARTIALLY CONFIRMED** — no version parameter; hash is meaningless |
| C3.9 | Drive revision lists can be incomplete | **CONFIRMED**, and understated |
| C3.10 | `files.export` bytes are content-hashable for reproducibility | **REFUTED — measured** |
| C3.11 | Pairing `revision_id` with a hash of exported bytes | **INCOHERENT** — export cannot target a revision |

#### C3.a · `spec-driven-with-adr` does not exist

```
$ openspec schema which spec-driven-with-adr
Error: Schema 'spec-driven-with-adr' not found
Available schemas: spec-driven
```

Zero occurrences of the string anywhere in the OpenSpec repo. `spec-driven` is the only built-in.
The plan's central framing — *"each change package should also emit an ADR using the
`spec-driven-with-adr` extension pattern"* — cites a feature that isn't there.

What *is* real, and is the correct citation if the plan wants this:
- `openspec schema fork spec-driven with-adr` genuinely writes `openspec/schemas/with-adr/schema.yaml`.
  That is the only circumstance under which the plan's claimed path is correct; `openspec init`
  creates no `openspec/schemas/` directory. Resolution order is project → user `$XDG_DATA_HOME` →
  package.
- A community **`intent-driven`** schema already does ADRs. Cite it as prior art instead of inventing
  a built-in.

Given §A3 — this repo does not run the OpenSpec CLI at all, and `openspec/specs/` is deliberately
unpopulated — the practical consequence is that the plan's schema argument is doubly inapplicable:
it invokes a feature that doesn't exist, in a tool this repo doesn't execute.

#### C3.b · ADRs inside a change do **not** persist — verified by running it

Live test. Before archive: `changes/add-export/adr/0001-use-streaming.md`. After `openspec archive`:
`changes/archive/2026-09-05-add-export/adr/0001-use-streaming.md`.

`archive` calls `moveDirectory(changeDir, archivePath)` with no allowlist — the entire folder moves,
`specs/**` deltas included. So the plan's stated rationale for the `adr/` folder ("ADRs persist
outside the archived change and let future proposals reuse prior reasoning") is the exact opposite
of what happens: the ADR gets buried in the archive.

This independently confirms §A4 from the tool's side. Put ADRs outside `openspec/changes/` —
which, in this repo, means `docs/decisions/NNNN-*.md`, where they already belong.

#### C3.c · Delta-format corrections worth carrying into any rewrite

Exact validator regex (`src/core/parsers/spec-structure.ts:5`), case-insensitive:

```
/^##\s+(ADDED|MODIFIED|REMOVED|RENAMED)\s+Requirements\s*$/i
```

- **`RENAMED` is a fourth operation** the plan omits. Syntax: `- FROM: \`### Requirement: Old\`` /
  `- TO: \`### Requirement: New\``.
- ADDED and MODIFIED each require **≥1 scenario** (error: `ADDED "<name>" must include at least one
  scenario`). REMOVED is names-only and needs `**Reason**` + `**Migration**`.
- Scenarios must use **exactly four hashtags**; the check is fence-aware.
- **MODIFIED must carry full content** and may not drop scenarios the live spec still has. This is
  the rule that bites §A2: Change 4's requirement is a MODIFIED, and as a stub it would fail.
- New capabilities need a `## Purpose` of 50+ characters under `--strict`.
- `design.md` is gated on cross-cutting change, a new external dependency, a data-model change,
  security/performance/migration complexity, or ambiguity — a change without one passes
  `--strict` (tested).
- Unknown subfolders in a change dir are harmless to validation, so the `adr/` folder fails on
  purpose (§C3.b), not on syntax.

#### C3.d · Change 3's flagship ADR is empirically refuted

ADR 0003 in the plan — *"content-hash every retrieved source regardless of its native revision
system's completeness guarantees"* — is presented as the strongest unique discovery in the whole
synthesis. Its premise is confirmed; its mechanism does not work.

**The premise is right, and understated.** Google's own wording (Drive v3 discovery, rev 20260901):

> **Important:** The list of revisions returned by this method might be incomplete for files with a
> large revision history, including frequently edited Google Docs, Sheets, and Slides. Older
> revisions might be omitted from the response… The revision history visible in the Workspace editor
> user interface might be more complete than the list returned by the API.

Two harder limits the plan omits: `keepForever` is *"only applicable to files with binary content in
Drive"* — so **Google-native docs cannot be pinned at all** — and editor revisions *"may be merged
together."*

**The mechanism is refuted, by measurement.** Same unmodified doc, exported to DOCX twice, six
seconds apart:

```
export1  317966 bytes  sha256 b1a97bbc…cad01
export2  317966 bytes  sha256 f0ad06f5…d2d21     IDENTICAL BYTES: False
first differing offset: 10   (ZIP DOS timestamp field)   28 differing positions
ZIP entry mtimes: 2026-09-04 20:26:54  vs  20:27:00   ← export wall-clock, not document mtime
```

DOCX export is **not byte-stable**. PDF export happened to be identical across two calls — Google's
PDF carries no `/CreationDate`, `/ModDate` or `/ID` — but its Info dict is
`/Producer (Skia/PDF m154 Google Docs Renderer)`, so **a renderer upgrade to m155 silently
invalidates every stored hash with zero document edits**. Determinism is format-dependent,
undocumented and unguaranteed. Corroborating: `Revision.md5Checksum` is *"only applicable to files
with binary content"* — Google computes no content hash for native docs.

**And the pairing is incoherent.** `files.export` takes only `fileId` and `mimeType`. **There is no
`revisionId` parameter** (and a 10 MB cap). Per-revision export exists only via
`Revision.exportLinks` off `revisions.get`/`list` — a different call path. Storing `revision_id`
beside a hash of *current* export bytes pairs two things with no causal link: the document can
change between the revision read and the export.

**Fix:** rewrite the requirement as *"export via `Revision.exportLinks` for the named revision, hash
the returned bytes, and record the export MIME type and — where obtainable — the renderer/producer
string, treating the hash as a change-detector rather than a reproducibility key."* Or drop the hash
and store the exported artifact itself, which is what actually makes the corpus replayable. Either
way, `content_sha256` as specified will produce spurious mismatches on every re-export, and a scorer
gated on it would flake continuously.

#### C3.e · Context7 has no version parameter

`query-docs` accepts exactly `{libraryId, query}` and calls `GET /api/v2/context?query=&libraryId=`.
Version is expressible only as a **path segment** (`/org/project/version`), only for libraries that
publish versions, and the response never echoes it back. The response body is `await response.text()`
— a plain blob with no metadata, no ETag, no snapshot ID.

So the plan's scenario — *"it SHALL store the resolved library ID, requested version, and a content
hash of the returned documentation snippet"* — has one field that isn't a parameter and one hash
that isn't meaningful: the blob is relevance-ranked output from a continuously re-crawled index and
will churn for reasons unrelated to the docs changing.

Tool names are current: the `get-library-docs` → `query-docs` rename landed in
`@upstash/context7-mcp` v2.0.0.

**What is actually recordable via MCP:** Title, library ID, Description, code-snippet count, Source
Reputation, Benchmark Score, `Versions[]`, Source. The genuinely useful provenance fields —
`lastUpdateDate`, `branch`, `state`, `totalTokens` — exist on the API type but are **not rendered**,
so they are unreachable through MCP. Record library ID + pinned version segment +
`resolve-library-id` output verbatim, and drop the content-hash idea.

### C4 · Requirements quality and judge calibration

| # | Claim | Verdict |
|---|---|---|
| C4.1 | TSE 2026: LLMs match humans on coverage/style but show **lower diversity** | **CONFIRMED**, but the metric does not mean what the plan uses it for — see C4.a |
| C4.2 | arXiv 2603.28163: SOTA models slightly exceed humans | **PARTIALLY CONFIRMED**, title misattributed; it *corroborates* C4.1 |
| C4.3 | Austrian Post field study, 6 agile teams, effective in production | **PARTIALLY CONFIRMED** — far weaker than described, see C4.b |
| C4.4 | CIBSE INVEST paper: 5/5 medians, >85–90% agreement, ρ≈0.53–0.65, GPT-5.1 | **SOURCE NOT FOUND** — see C4.c |
| C4.5 | 29148 → three reliably LLM-assessable attributes; "INCOSE-aligned seven-trait narrowing" | **MISATTRIBUTED** — see C4.d |
| C4.6 | Doc-to-code traceability "below 58% strict" | **PARTIALLY CONFIRMED** — o3-mini reaches 71.1% |
| C4.7 | κ CI width 0.10 at N=200 (400 if κ<0.4); ±10pp at n≈100, ±5pp at n≈400 | **κ half UNSUPPORTED** (wrong by 4–6×); **proportions CONFIRMED** — see C4.e |
| C4.8 | Arize human–LLM judge alignment guidance | **CONFIRMED**, but states no threshold and no sample size |
| C4.9 | arXiv 2510.09738 Turing-test z-score | **CONFIRMED on substance**, title misattributed — see C4.f |
| C4.10 | Langfuse: one failure mode, TPR/TNR >90% on dev, then held-out test | **CONFIRMED with caveat** — ">90%" is written "e.g." |
| C4.11 | AWS GEDD Cohen's-kappa-for-LLM-judges doc | **CONFIRMED** — and it contradicts C4.7 |

#### C4.a · The diversity finding is real, and the plan's use of it is not

This is the plan's flagship unique discovery, so it matters that the metric is misread three ways.

The finding is confirmed: students score 98.58% diversity, LLMs 44.23% (Claude 3 Sonnet) to 74.74%
(Grok Beta). But:

1. **The human comparator is 30 students, not domain experts.** "Lower diversity than humans" means
   lower than students on a course exercise.
2. **It is a *between-run* metric.** Diversity = `100 − coverage` at cosine ≥0.80
   (text-embedding-3-small), averaged pairwise **across 30 generator instances**. The plan applies it
   as a floor on the internal diversity of *one model's single backlog*. That is a different
   quantity; a model can produce a varied single backlog and near-identical backlogs across runs, or
   the reverse.
3. **A hard floor is gameable by a temperature knob.** The paper says outright: *"Increasing the
   temperature parameter beyond the default value can enhance the diversity of LLM outputs."* A gate
   that a config change satisfies is a proxy metric of exactly the kind the plan's own risk slide
   warns about.
4. The plan also understates the paper: LLMs **outperform** students on coverage (73–96% vs 52.83%),
   they do not merely "match."

**Disposition:** keep `req_semantic_diversity`, keep it as a **floor routed to `escalate`** (the plan
gets that part right), but (a) define it *within* a backlog and say so, (b) pin generation
temperature in the target config and treat a temperature change as a protected-path change, and (c)
drop "nobody in your peer set is measuring this" — the framing is stronger without the boast, and
the boast is the part that invites the reviewer to check.

arXiv 2603.28163's real title is *"**From Reviews to Requirements:** Can LLMs Generate Human-Like
User Stories?"*; its "SOTA" models are GPT-3.5 Turbo and Mistral 7B; the human-exceeding margin is
**0.14 on a 5.0 scale with no significance test**; and its Table 2 independently *reproduces* the
diversity deficit (human 0.32 Independent / 0.33 Unique vs LLM 0.26–0.29 / 0.29–0.31). The plan
presents it as a counterweight to C4.1. It is a corroboration.

#### C4.b · "Austrian Post field study across 6 agile teams" oversells the evidence considerably

Austrian Post ✓, six teams ✓. But the study used **25 synthetic stories**; the practitioner survey
covered **two** of them; n = 11–12 raters (the paper self-contradicts, abstract 11, results 12); no
control group; self-reported Likert outcomes; and the paper labels itself an *"early report."* It
also contains counter-evidence the plan omits: GPT-4-improved stories scored **worse** on size
(3.00 and 3.17), with six participants complaining they were too long.

"Effective at improving story quality in production" is not what this shows. "Promising in a small
practitioner survey at one organization" is.

This weakens — but does not kill — the plan's best strategic suggestion (pitch Scenario C as a
quality gate on human-written stories before pitching it as a generator). That reframing is still
right; it just cannot lean on this citation as industrial precedent.

#### C4.c · One cited source could not be found at all

The exact title *"LLM-Assisted INVEST Evaluation and Improvement of User Stories"* returns **zero
matches** in quoted search anywhere. The `sol.sbc.org.br` host was egress-blocked in this session, so
this is **SOURCE NOT REACHED** rather than proven nonexistent — the article-ID range is plausible for
CIbSE 2026, and GPT-5.1 is not anachronistic for a 2026 camera-ready.

What makes it worth flagging anyway: the claimed statistics track a **different, verifiable** paper
closely — *DeepQuali* (Fraunhofer IESE, arXiv 2602.08887), which uses **GPT-4o**, 5 user stories and
4 experts, and reports Spearman ρ of 0.32–0.61 for **Independent (0.50/0.32) and Small (0.55/0.55)**.
Those are **expert-vs-expert** agreements, not model-vs-expert. DeepQuali also states explicitly:
*"we did not calculate tests of statistical significance."*

If the plan's "ρ≈0.53–0.65, model ran conservative on Independent and Small" came from there, an
inter-rater agreement has been reattributed as a model–expert agreement. That is a category error,
and it is the one claim in the plan I would not repeat in front of anyone until the primary is read.

#### C4.d · The ISO 29148 attribution breaks in three places

ISO/IEC/IEEE 29148:2018 enumerates **nine** individual-requirement characteristics: Necessary,
Appropriate, Unambiguous, Complete, Singular, Feasible, Verifiable, Correct, Conforming.

- **"Essential" and "Independent" are not 29148 terms.** They come from one 2026 arXiv paper
  (2604.15222, Levy et al.), verbatim: *"The traits Necessary and Appropriate were replaced with
  Essential and Independent… The terms Correct and Conforming were excluded… Thus, the review process
  focused on seven key attributes."*
- **"INCOSE-aligned seven-trait narrowing" is that one paper's private 9→7 adaptation, not an INCOSE
  construct** — and it narrows to **seven**, never to three. The plan's "three intrinsic,
  domain-independent attributes shown reliable by research" has no source that says that. The
  Springer RE-journal paper does use Unambiguity/Verifiability/Singularity, but as a **scoping choice**
  for an LLM-as-judge over 900 candidate requirements — not as a finding that the other six are
  unreliable. The MDPI citation is real but off-topic (it is about evaluating LLMs in RE tasks with
  no ground truth).
- **That source paper has an internal defect**: it says seven traits, then enumerates six (Complete
  is dropped). And its Table 6 assigns only **Essential and Feasible** to "Human Primary Driver / AI
  Limited" — so the plan's "report Essential/Independent/Complete/Feasible but never gate" grouping
  does not match the source either.
- **The decisive objection:** the same paper found **Claude Sonnet 3.5 at 85% agreement vs GPT-4 at
  45%** — a 40-point spread on the same attributes. LLM-assessability is **model-specific, not
  attribute-intrinsic**. Any gating rule that partitions attributes into "judge-safe" and
  "report-only" without naming the judge model is unsound at the root.

**Disposition:** this does not sink Change 3, but it means the judge-gated subset must be chosen
**empirically from this repo's own calibration run**, per attribute *and* per judge model — which is
exactly what `extend-judge-calibration` is for. Delete the appeal to a "narrowing" that does not
exist and let the calibration decide. Doing so also removes the plan's need to justify the choice
from literature at all.

On C4.6: quote the real bound. Table 5 reports Claude 3.5 44.7%/57.6%, GPT-4o 42.9%/48.5%, **o3-mini
54.8%/71.1%**. "Below 58% strict" is true only of the weaker models, and "strict" there means
LLM-judged *explanation* quality, not trace accuracy — one-to-many F1 is 79.4%. The plan's underlying
point survives (traceability must be measured, never inferred), but the number as written will not.

#### C4.e · The κ sample-size thresholds are wrong by 4–6×, and this is written into a spec

The plan's Change 4 spec scenario hard-codes: *"a calibration set smaller than 200 paired labels with
measured kappa between 0.5 and 0.7 (or smaller than 400 for kappa between 0.3 and 0.4)"* for a stated
**"CI width of 0.10."** The cited source is a Reddit thread (**NOT REACHED** — reddit.com is
egress-blocked here).

I re-derived this independently rather than trusting either the plan or the check. For two raters
with balanced marginals, `Pe = 0.5`, `κ = 2·Po − 1`, so `Var(κ) = 4·Po(1−Po)/N`:

| true κ | CI width @ N=200 | CI width @ N=400 | N for **width** 0.10 | N for **half-width** ±0.10 |
|---:|---:|---:|---:|---:|
| 0.30 | 0.264 | 0.187 | 1398 | 350 |
| 0.40 | 0.254 | 0.180 | 1291 | 323 |
| 0.50 | 0.240 | 0.170 | 1152 | 288 |
| 0.60 | 0.222 | 0.157 | 983 | 246 |
| 0.70 | 0.198 | 0.140 | 784 | 196 |

At N=200 and κ=0.5 the actual 95% CI width is **0.240**, not 0.10. Reaching width 0.10 needs
**~780–1,400** paired labels, not 200–400. (Independent Monte Carlo over 20,000 runs agrees: empirical
SD 0.0608 → width 0.239 vs 0.240 analytic.) Skewed marginals are much worse: at 20% prevalence,
κ=0.5 needs N≈1,801; at 10% prevalence, N≈3,201 — and a "does this generated requirement hallucinate
scope?" label set will be skewed.

**The charitable reconstruction is almost certainly the right one:** read as a **half-width** of
±0.10 (total width 0.20), the numbers land at N≈196 for κ=0.7 and N≈350 for κ=0.3 — i.e. exactly
"200" and "400+". The source conflated half-width with width, and the plan inherited it.

**Fix, and pick one:** either state **±0.10 half-width** and keep ~200/~350, or keep "width 0.10" and
state **~800–1,200**. Do not ship both. Whichever is chosen goes on a frozen `*Config` field, not in
requirement prose (§A13).

Two further corrections:
- The **proportion** figures are textbook-correct: ±9.80pp at n=100 and ±4.90pp at n=400 (Wald, worst
  case p=0.5). Keep them.
- **Do not cite Bujang & Baharum's tables alongside this.** They are **power**-based (80% power,
  testing H0: κ=κ₀), a different target than fixed CI width, and they instruct doubling N for unequal
  marginals. Conflating the two produces a third incompatible number. The right anchors for
  CI-width sizing are Donner & Eliasziw (1987/1992) and Sim & Wright (2005).

**And the plan cites two sources that contradict each other.** AWS GEDD (C4.11) recommends **25–40
(active learning) or 60–80 (random) total annotations** and warns that <10 gives a CI "wider than
±0.30." That warning is true but badly understated — at n=10, κ=0.6 the half-width is **±0.50**; at
n=30 it is ±0.29; at n=80 it is ±0.18. Meanwhile GEDD's own decision bands ("Moderate: usable with
human review" 0.41–0.60 vs "Substantial: acceptable for automation" 0.61–0.79) are **0.20 wide**, so
placing a κ in the right band needs half-width ≈0.10 → **n ≈ 250**. Its recommended 25–80 cannot
resolve the gate it prescribes. Citing GEDD and the Reddit figure together puts **three mutually
incompatible numbers (25–80, 200–400, ~1,000)** into one spec.

This is, structurally, the same defect class as **F-049** — a health floor that computes a
CI width over an operating region and fails open when the region is empty. The plan already
identifies F-049 as a compelling narrative thread. It is a better one than the plan realizes:
this is that bug, in the plan's own calibration gate, before it ships.

#### C4.f · The z-score is real; its denominator is three numbers

The formula is verbatim in arXiv 2510.09738 — the plan reproduces it correctly. Three caveats before
it goes on a slide as "a single number answering *is your AI grader as good as my engineers?*":

- The paper's real title is *"**Judge's Verdict:** A Comprehensive Analysis of LLM Judge Capability
  **Through Human Agreement**."* Cite it fully.
- **σ_human is a standard deviation over exactly three pairwise kappas**, with no reported CI. That
  is a very noisy denominator, and the z-score inherits all of it.
- All |z| < 1 models sit in a κ band of 0.753–0.816, so the instrument discriminates within ~0.06.
  The task is RAG answer-accuracy on a 0/0.5/1.0 scale; transfer to user-story or RCA judging is
  unestablished. It is an unpublished preprint.

On C4.10: Langfuse's ">90% TPR/TNR" is written **"e.g."** — an illustration, not a standard. The plan
promotes it to a gate threshold. Langfuse gives no dev/test set size guidance either, so it cannot
back C4.7. On C4.8: Arize's guidance is real and sound (establish a human–human baseline, compare on
the same metric, report P/R/F1) but contains **no numeric threshold and no sample size** — it also
cannot back C4.7.

**Net on Part C:** of the plan's ~25 load-bearing citations, **11 are confirmed as stated**, **9 are
partially confirmed with corrections that change the number or the scope**, **3 are misattributed**,
**1 is refuted by measurement**, and **2 could not be found**. That is a better hit rate than most
strategy documents achieve — but the errors cluster in exactly the places the plan proposes to write
numbers into specs, which is the worst possible place for them.

---

## Part D — Recommended disposition

0. **Fix the dependency graph first.** The plan's root node is judge calibration. It is not. The
   real ordering is: CHARTER §6 amendment (or re-scope to synthetic corpora, §A16) →
   `prove-m8-execution` (§A17) → report-only gate rules (§A6) → scorers. Judge calibration
   (§A1) is a leaf that is already in flight.
1. **Drop Change 4.** Fold "calibration artifact must carry κ, N and a CI, and gating is refused
   below the floor" into `openspec/changes/extend-judge-calibration/` as a `## MODIFIED
   Requirements` delta on `require_calibration_for_judge_gating`. One change, not two.
2. **Add Change 0 — `add-report-only-gate-rules`.** `GateRule.report_only: bool` plus a
   `GateResult.advisory` channel, so a metric can be computed and recorded without blocking. Every
   other change depends on it. It is small, it is in a protected path, and it should land first.
3. **Cut the scorer count to what the first demo needs.** A defensible Sprint-1 target is ~12 total,
   not 35: testgen → `test_executability`, `testgen_mutation_score`, `testgen_green_on_correct`,
   `requirement_obligation_recall`; RCA → `rca_ac_at_k`, `rca_component_match`,
   `rca_onset_within_tolerance`, `rca_abstention_correctness`; requirements → `req_ac_recall`,
   `req_scope_hallucination`, `req_traceability_closure`, `req_semantic_diversity` (distinct-n).
   That is 60 matrix cells — large but survivable. Everything else is Sprint 3+.
4. **Re-home the corpora** out of `flow-corpus/` into a package chartered for real data, and reuse
   `flow_corpus.mutation` / `flow_corpus.holdout` rather than reimplementing them.
5. **Rewrite each change to this repo's layout:** `proposal.md`, `design.md`, `tasks.md`,
   `review.md`, `specs/<cap>/spec.md`; ADRs at `docs/decisions/0042+`; a `tasks.md` checkbox for
   `openspec/README.md` index registration; a checkbox for `public_surface_baseline.json` and
   `plugin_registry_baseline.json` regeneration; scorers as packages, not single modules.
6. **Move every number out of requirement text** onto frozen `*Config` fields, justified in
   `design.md`.
7. **Price the protected-path review latency** into the schedule, or say plainly that the timeline
   assumes same-day CODEOWNER turnaround.
8. **Drop the three claims that cannot be defended**: `spec-driven-with-adr` (C3.a),
   `counterfactual_support` (C1.e, §A9), and the "INCOSE-aligned seven-trait narrowing" (C4.d). Each
   is load-bearing rhetoric with nothing under it, and each is the kind of thing a hostile reviewer
   finds first.
9. **Fix every number that goes on a slide**, per Part C. Specifically: OpenRCA 11.3% → 12.5%, not
   10% → 33%; "35.9% of *instrumented code-plus-tests* PRs"; MTTR anchored to Meta's DrP (20%,
   measured, and not AI) rather than 30–70% vendor ranges; κ sizing stated as ±0.10 half-width with
   N≈200/350, or width 0.10 with N≈800–1,200 — one or the other.

### The three risks to name on the slide

The plan proposes naming proxy-metric validity, benchmark contamination, and judge self-gaming. Two
of those are right. Swap the third:

1. **Proxy-metric validity** — keep. Strengthen it with C1.a's `max-|Z|` result: a trivial heuristic
   scoring 36.5% on pooled RCA benchmarks is the most vivid possible illustration, and it is *your*
   baseline row, not a borrowed anecdote.
2. **Judge self-gaming** — keep. `extend-judge-calibration`'s three bias probes (order, verbosity,
   self-preference) are the answer, and they are already half-built.
3. **Benchmark contamination → replace with *gate-mechanism* integrity.** Contamination is a real
   risk but a generic one, and the internal-corpus-first decision already mitigates it. The sharper,
   more credible risk — and the one this repo has the better story for — is that a gate can look
   green while measuring nothing. You have three shipped instances to point at: F-049 (a CI-width
   floor that failed open on an empty operating region), `prove-m8-execution` (a composability
   dimension crediting config presence rather than execution), and C4.e above (a calibration
   threshold that would have shipped 4–6× undersized). Leading with "here are three times our own
   gates were wrong and how we caught them" is a far stronger credibility argument than any
   percentage, and it is the one claim in this whole programme that is fully evidenced today.

---

## Method and limitations

Repository claims were checked against the working tree at `28eb09d`; every file:line reference above
was read, not inferred. External claims were re-fetched independently; the κ sample-size table was
re-derived from `Var(κ) = 4·Po(1−Po)/N` and cross-checked against a 20,000-run Monte Carlo.

**Sources that could not be reached** (session egress proxy returned 403 CONNECT): `arxiv.org`
direct, `dl.acm.org`, `link.springer.com`, `mdpi.com`, `computer.org`, `openreview.net`,
`semanticscholar.org`, `reddit.com`, `sol.sbc.org.br`, `arize.com`, `langfuse.com`, `traversal.com`,
`irisagent.com`, `anthropic.com`. Most were routed around via the alphaXiv MCP (full paper text),
`raw.githubusercontent.com`, and search indices; where a claim rests only on an index snippet or a
triangulation, it is marked in place. **Two claims are unresolved**: the Inozemtseva primary PDF
(C2.d — triangulated from a verbatim restatement in the ISSTA 2026 replication, but confirm before
external publication) and the CIbSE INVEST paper (C4.c — no route found).
