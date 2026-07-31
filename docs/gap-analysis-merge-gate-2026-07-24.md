# Gap Analysis & Tech-Debt Report — merge gate / calibration, 2026-07-24

Scope: the merge-gate and calibration subsystem (`agent_core/{calibration,calibration_report,
outcome_store,merge_gate,merge_gate_ci,merge_seed,outcome_labeller,audit_sampler,store_sync}`,
`scripts/{merge_gate_context,agent_confidence}`) and its six workflows, read in full at
`961cfd14`. Companion to `gap-analysis-2026-07.md`, which covers the repo-wide picture.
Every finding below was reproduced before being recorded; the reproduction is quoted with it.

Written alongside the peer review in `plans/agent-record-decontamination/REVIEW.md`, which
prompted the sweep.

## 1. Baseline — what is already healthy

| Area | Result |
|---|---|
| `ruff check` / `ruff format --check`, pinned 0.15.20 | clean, 479 files |
| `mypy` root targets (`src/eval_harness`, `scripts`, `tests`), pinned 2.1.0 | clean — 28 / 67 / 60 files |
| `mypy --strict` on `agent_core` (package + tests) | clean — 33 source files |
| agent-core suite / coverage | 479 passed, 2 xfailed; **98.8%** branch vs gate 95 |
| root suite / coverage | 936 passed, 9 skipped; **96.35%** branch vs gate 96 |
| `flow-protocol`, `flow-corpus`, `behavioral-regression` gates | PASS |
| Wilson interval, AUROC, Brier, selective risk | single-sourced in `calibration.py`; no duplicate implementations |
| Domain namespace, YAML loading, subprocess running, atomic writes | single-sourced (`domains.py`, `scripts/_config.py`, `subprocess_util.py`, `atomic_io.py`) |
| `# type: ignore` / `cast()` / missing return annotations in the subsystem | **zero** |
| numpy | still not used anywhere, deliberately (`calibration.py` is pure-Python by design). Restating `gap-analysis-2026-07.md`: "enable numpy lint" remains a conscious no-op |

## 2. Fixed in this pass (four defects)

### F1 — Out-of-contract confidences reached AUTO_MERGE (fail-open) — FIXED

`NaN` compares False against every bin edge, so `BinningCalibrator.bin_index`'s scan fell
through to its `score >= top edge` return — the *highest*-confidence bucket. Values above
1.0 landed there too. Values below 0 escalated, so the failure was one-sided toward unsafe.
Reproduced with a trustworthy calibrator:

```
raw_confidence=0.95  -> auto_merge      raw_confidence=nan  -> auto_merge
raw_confidence=5.0   -> auto_merge      raw_confidence=-3.0 -> escalate
```

Latent only because no domain currently has a trustworthy calibrator (zero `HUMAN_AUDIT`
records ⇒ `tau is None` everywhere); it activates exactly when the gate goes live.
`ChangeContext.__post_init__` now enforces the `[0, 1]` contract its field comment always
claimed, `bin_index` floors any non-finite or out-of-range score to bin 0 for records that
arrive straight from the store,
and `merge_gate_ci` reports bad input as exit 2 (usage) rather than 1 — never 0, which CI
reads as proceed-to-merge.

### F2 — `evaluate_calibration` passed slices that cannot evidence discrimination — FIXED

`passes` included `(roc is None or roc >= auroc_target)`, so an undefined AUROC satisfied
the resolution criterion vacuously. A forecaster wrong 100% of the time is perfectly
calibrated against its own base rate, so it cleared ECE/MCE too:

```
n=12 all-wrong @conf=0.0 -> auroc None, ece 0.0, PASSES True
n=1  single record       -> auroc None, ece 0.0, PASSES True
```

Degeneracy is now always reported on `CalibrationReport.degenerate` and logged at WARNING;
enforcement is opt-in via `min_samples` / `require_discrimination` (`CalibrationConfig`),
both defaulting to the prior behaviour. An all-correct golden set is a legitimate shape, so
it keeps passing until a caller opts in.

### F3 — `build_domain_models` decided autonomy silently — FIXED

The `HUMAN_AUDIT`-only filter dropped every other record with no count and no log, so an
all-passive store was indistinguishable from an empty one — which is today's live state
(43 records, 12 labelled, **0 audited**). It now reports exclusions by reason and warns when
no audit records exist at all.

### F4 — `store_sync` and `OutcomeStore` had contradictory parse contracts — FIXED (ADR 0025)

`store_sync/serialization.py` deliberately preserves an unparseable line as "opaque" so a
rolling upgrade never loses data; `OutcomeStore.all()` raised `TypeError` on that same line,
strict by design (`jsonl.py`). Both rationales were right for the failure they guarded, but
`OutcomeRecord(**json.loads(line))` could not tell an **unknown extra key** from a **missing
required key** — both raise `TypeError` — so the mechanism built to survive a rolling upgrade
produced exactly the record that broke every other consumer. Reproduced on a two-line store:

```
store_sync:    parsed=1 opaque=1
OutcomeStore:  TypeError: OutcomeRecord.__init__() got an unexpected keyword argument 'future_field'
```

Blast radius: `merge_gate_ci` exits 1 in both the gate and shadow jobs (every PR fails), and
`outcome_labeller` / `audit_sampler` / `merge_seed` have no handler at all.

`OutcomeRecord.from_json` now distinguishes additive schema evolution from corruption: unknown
extra fields are dropped and logged, while malformed JSON, a non-object payload, a missing
required field, and wrong types all still raise. `store_sync` is untouched — it calls the
constructor directly, so it still classifies such a line as opaque and round-trips it verbatim.
Both invariants hold at once, and a test now crosses the seam in one assertion, which neither
module's suite previously did.

## 3. Fixed since this report (F-049, ADR 0029, 2026-07-31)

An independent re-verification (`openspec/changes/merge-gate-health-integrity/review.md`)
confirmed G1–G3, closed all three, found G3's own stated mechanism wrong, and found the
severity of G3 understated — it reproduces to `AUTO_MERGE` under stock `GatePolicyConfig()`.
It also substantially refuted G5's headline claim. Kept here rather than deleted so the
reproductions remain a record of what shipped broken.

### G1 — `GatePolicyConfig` is unreachable from any config or CLI (HIGH) — FIXED (F-049, ADR 0029)

`merge_gate_ci.py` constructs `GatePolicyConfig()` bare; the only other construction is a
validation script. So `risk_target`, `min_calibration_n`, `max_ece`, `min_auroc`,
`wilson_floor` — the values that govern autonomy — can only change by editing library
source. Every sibling config (`ReportConfig`, `AuditConfig`, `LabellerConfig`,
`StoreSyncConfig`) is CLI-reachable. It also has no `__post_init__`, so it accepts
`risk_target=1.0` and `min_calibration_n=0`.

**Fix:** `GatePolicyConfig.__post_init__` bounds all nine tunables (plus the new `n_bins`),
and `merge_gate_ci` exposes one CLI flag per tunable with an exit-2 usage path. Bounds follow
one rule: reject the vacuous endpoint, allow the maximally strict one. `n_bins` additionally
carries an upper bound (`MAX_N_BINS = 1000`) with a distinct resource-safety rationale, added
after peer review found the newly CLI-reachable bin count could drive real CI wall-clock cost
(see G2's fix note).

### G2 — Four independent equal-width binning implementations (HIGH) — FIXED (F-049, ADR 0029)

`calibration.py` (reliability bins), and three in `outcome_store.py`
(`BinningCalibrator.fit`, `BinningCalibrator.bin_index`, `_upper_half_ci_width`). They agree
on in-range inputs — bin edges are float-exact, verified — but `fit` and `bin_index` disagree
out-of-range, which is what made F1 reachable. The bin count `10` is a default in three
places that must silently agree; `GatePolicyConfig` has no `n_bins` field, so the ECE in
`CalibratorHealth` is computed over a different binning object than the calibrator it
measures.

**Fix:** score-to-bin routing is single-sourced in `_bin_of`; `fit`, `bin_index`, and the
operating-region width all delegate to it (via the shared `_bucket_by_bin` grouping helper).
The bin count is single-sourced (`calibration.DEFAULT_N_BINS` as the library default,
`GatePolicyConfig.n_bins` as the tunable) and threaded explicitly at every call site.
**Peer-review addendum:** the first version of this fix regressed `fit`'s and the
operating-region width's complexity from O(n_bins·n) to O(n_bins²·n) by calling `_bin_of`'s
own O(n_bins) scan once per `(bin, score)` pair instead of once per score — measured at
~3.8s for `n_bins=200` on 5000 scores, a real hang/timeout risk once the bin count became
CLI-reachable. `_bucket_by_bin` assigns each score to its bin exactly once and groups,
restoring O(n_bins·n); verified bit-for-bit identical to the pre-fix output across every
`n_bins` tested, and benchmarked at ~0.02s for the same case (190×).

### G3 — `_upper_half_ci_width` returns 0.0 for "no data", which passes a health floor (HIGH) — FIXED (F-049, ADR 0029)

A domain whose entire audit history sits below confidence 0.5 gets `bin_ci_width = 0.0`,
vacuously satisfying `bin_ci_width <= max_bin_ci_width`. "No evidence" scores identically to
"strongest possible evidence". ~~The same `wilson_interval(0, 0) -> (0.0, 0.0)` return is
fail-closed at its *lower-bound* call site and fail-open at this *width* one.~~

**Correction (re-verification):** the stated mechanism above is wrong. `wilson_interval(0,
0)` is never reached inside `_upper_half_ci_width` — `if not idx: continue` returns before
it. The fail-open is the `widest = 0.0` initialiser: the identity element of a
`max`-reduction over an empty set. Hardening `wilson_interval` would not have fixed this.

**Correction (severity):** reproduced to `AUTO_MERGE` under stock config — this was not a
latent hygiene issue. 6600 `HUMAN_AUDIT` records at `raw_confidence ∈ {0.05, 0.45}` gave
`CalibratorHealth(n=6600, ece=0.0, auroc=1.0, bin_ci_width=0.0)`, `is_trustworthy=True`,
`tau=1.0`, and `decide(raw_confidence=0.45) == AUTO_MERGE`. The function also measured the
wrong axis: `decide()` gates on the *calibrated* `p`, not the raw score, so "the upper half
of the raw range" was never "where auto-merges actually happen" as the removed docstring
claimed.

**Fix:** `_operating_bin_ci_width` defines the eligible region by the per-decision Wilson
floor (a bin whose Wilson upper bound cannot reach `wilson_floor` can never be an operating
point, whatever `tau` becomes — tau-free and computable at health time, since `tau` is
derived *from* health) and returns `None`, not `0.0`, when nothing qualifies.
`is_trustworthy` rejects `None` before comparing it to `max_bin_ci_width`. Full design
rationale, including why a sentinel-only fix was rejected as insufficient, in
[ADR 0029](decisions/0029-operating-region-calibrator-health.md).

## 4. Open findings, highest severity first

### G4 — Four CLI summaries can never be emitted (MEDIUM) — widened, still open

`calibration_report` and `merge_seed` log their only structured run record at INFO but never
call `configure_logging`, so at the root logger's default WARNING the lines are discarded.
`merge_gate_ci` and `store_sync` do configure it. **Re-verification widened this finding**:
`outcome_labeller` and `audit_sampler` gained real logging since this report was written (see
G5), but neither calls `configure_logging` either — so the same defect now applies to 4 CLIs,
not 2. None of the four can change a gate decision.

### G5 — `outcome_labeller` and `audit_sampler` have no logging at all (MEDIUM) — headline claim REFUTED; one sub-claim still open

~~Both write labels — `audit_sampler.record_verdict` writes the *authoritative* `HUMAN_AUDIT`
label — using `print` only.~~ **Refuted by re-verification**: both modules gained real
`logger.debug`/`.info`/`.error` calls since this report was written. The residue is folded
into G4 above.

`outcome_labeller` writes a weak optimistic positive (`TIMEOUT_CLEAN, True`) whenever its
fail-safe detectors report no signal, with no record of why. `record_verdict` is also
non-idempotent; the SHA validation and already-audited no-op live in the
`scripts/record_audit_verdict.py` wrapper, which the library CLI bypasses. **This sub-claim
is confirmed accurate and remains open** — the library docstring states the split is
deliberate, so a fix is contested rather than merely deferred.

### G6 — `scripts/_config.py::load_yaml_mapping` returns bare `dict` (MEDIUM)

`dict[Any, Any]` makes every subscript of a loaded config `Any`, silently disabling type
checking inside `DomainMapping.load`, `AgentIdentity.load`, and `ProxyConfig.load`. The
runtime `isinstance` guards compensate, so this is checker debt rather than a live bug;
`-> dict[str, object]` restores it.

### G7 — Two `configure_logging` implementations with different formats (LOW)

`agent_core/logging_util.py` (string level, validated) and `scripts/_cli.py` (int level,
`verbose` bool). A single CI run emits merge-gate logs in two different formats.

### G8 — Unreachable branches counted against the coverage budget (LOW)

`calibration.py`'s `IsotonicCalibrator.predict` has two provably dead lines — `fit`
pre-aggregates ties, so `_x` is strictly increasing and `x1 == x0` cannot occur, and the
post-loop return is shadowed by the `prob >= _x[-1]` guard above it. Neither is in
`exclude_also`.

### G9 — `agent_confidence.py` is missing from one CI coverage gate (LOW)

`quality-gates.yml` names an explicit module allowlist that omits it; it is covered only via
`eval-harness-ci.yml`'s by-directory run. The module computing every `raw_confidence` written
to the store has an 85% floor in one job and none in the other.

## 5. Test gaps worth closing

- `build_domain_models`'s held-out-fold contract is untested: the healthy-domain test uses
  perfectly separable data, so a mutant evaluating on the fit set would pass. The docstring's
  central promise ("the risk threshold is not overfit") has no test.
- `select_for_audit` is only ever tested with a **single** domain, so the module's headline
  feature — per-domain stratification — is unexercised.
- `outcome_labeller`'s precedence order is tested one branch at a time, never with two
  signals true at once, so revert-wins-over-CI-failure is unpinned.
- ~~No test crosses the `store_sync` → `OutcomeStore` seam.~~ Closed by F4: one test now
  writes an opaque line, asserts `store_sync` preserves it, and reads it back through
  `OutcomeStore` in the same assertion.

## 6. Toolchain note

A local `make check-all` can fail `mypy` on `src/eval_harness/phoenix_client/__init__.py`
(`trace.get_tracer`) when `opentelemetry` is present transitively via the unpinned
`langfuse>=2`. `get_tracer` exists at runtime; uninstalling the package makes the typecheck
pass. This is a new instance of the local-vs-CI divergence already documented in
`pyproject.toml`'s mypy section for `phoenix-evals`/numpy stubs, and argues for pinning the
optional extras that reach the type checker.
