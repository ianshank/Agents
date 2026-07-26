# Design: add-measurement-harness-wedge

Technical design for the change. Promotes to a numbered ADR at land (next-free number; verify
— 0026 is taken by the proxy-correlation/PPI estimator). Format follows the house ADR idiom
(Context / Decision / Consequences).

## Context

The wedge must produce a defensible number on a repository the author does not own. Four facts
in this repo bound what that number can be:

| Fact | Evidence | Consequence |
|---|---|---|
| `raw_confidence` is a diff-shape heuristic, not agent belief | `scripts/agent_confidence.py:11-14`, ADR 0023 §1 | The report measures a *proxy*, and must say so in-band |
| Expected AUROC 0.5–0.65 vs a `min_auroc` floor of 0.65 | ADR 0023 §1; `merge_gate.py:49` | The signal is predicted to fail the system's own health gate |
| Only `HUMAN_AUDIT` feeds tau/health; live store has zero | ADR 0005 §3-4; `outcome_store.py:226` | No calibration is possible; a truth-side seam is required |
| `GatePolicyConfig` unreachable from config/CLI | G1, `docs/gap-analysis-merge-gate-2026-07-24.md` | A partner cannot re-tune the risk appetite |

There is also **no AUROC confidence interval anywhere in the repo** — `calibration.auroc:163`
returns a bare float. Since the product *is* honest uncertainty about discriminative power,
that is a prerequisite, not a nicety: an AUROC of 0.62 at n=14 must visibly straddle 0.5.

## Decision

### 1. Statistical only — no LLM, ever, in this path

External PR text (titles, bodies, diffs, comments) is an untrusted prompt-injection surface.
Excluding models also buys byte-for-byte determinism (required for golden tests and for a
credible "reproducible from the same history" claim) and preserves the air-gap/self-hosted
differentiator. Rendering is escaped and script-free; a static file with no `<script>` element
cannot execute injected content even if escaping failed.

### 2. Ingestion behind `PRHistorySource`, `gh`-first

Two implementations: `LocalGitSource` (fully offline) and `GhCliSource` (shells `gh pr list
--json …` through the existing `subprocess_util.run_failsafe`). `gh` is already a de-facto
dependency of `detectors.py`, and this inherits auth, pagination, and rate-limiting for free at
roughly a fifth the surface of a hand-rolled REST client. A `GitHubRestSource` is deferred.

**Read-only enforcement is two-part, because scope introspection alone cannot work.**
Classic-PAT `repo` is simultaneously the only scope granting private-repo *read* and a write
scope; fine-grained PATs, App tokens, and `GITHUB_TOKEN` return no `X-OAuth-Scopes` header at
all. So: (a) fail closed when scopes are unverifiable, with an explicit opt-out recorded in the
report manifest; and (b) a **static AST proof** in the F-ID gate that the module only ever
issues read verbs. (b) is the guarantee that actually holds.

**Truncation is representable, never silent.** `merged_prs` returns an `IngestResult` carrying
`truncated`, `reason`, and per-reason `skipped` counts. Silent truncation biases the corpus
toward recent PRs — the same disease as G3, where absence of evidence reads as evidence.

### 3. Two-phase mapping; the write boundary is proved by absence

Ingestion emits **pending** records only (`merge_seed.seed_pending`, which hardcodes
`label=None`); passive labels come from running the existing `outcome_labeller` against the
external clone. This adds zero new label logic.

A type-level guarantee is impossible — `label_source` is a plain `str | None` and ADR 0025
makes that deliberate, so older readers keep parsing newer files. Three layers instead:
`PassiveOnlyStore.append` rejects any non-passive source at the write boundary; a test asserts
rejection for `"human_audit"` *and* for an unknown string; and the F-ID gate AST-asserts that
no ingestion module references `HUMAN_AUDIT`, `record_verdict`, or `audit_sampler` at all.
Proof by absence is the only form that survives a later refactor.

### 4. Partner-supplied attribution is first-class

`config/agent-authors.yaml` knows exactly one head-ref prefix, `claude/`, and
`config/agent-confidence.yaml`'s `test_globs` and protected-path signal are this repo's. Left
as defaults, a partner using Copilot/Devin/Cursor routes **every** PR to the human lane at
`raw_confidence = 0.0` and the tool has nothing to say. Attribution rules, test globs, and
protected globs are injected at the CLI layer — no `config/**` edit, which is also a protected
path.

Offline mode carries one real limitation: a squash merge preserves no head-ref anywhere in git
history, so on a squash-merge repo `LocalGitSource` would report zero agent PRs. A
`--head-ref-from {merge-subject,trailer,none}` fallback plus an explicit provenance note keeps
that from reading as a bug.

### 5. The report leads with degeneracy — reordered, not restyled

When the PRIMARY view has zero labelled records or every slice is degenerate, the document
opens with a banner naming exactly what is missing, then provenance, and the metric tables come
last. Tested by asserting the banner's character index precedes the first table.

`_shape_degeneracy`, `proxy_eval`'s withholding conventions, and `ppi.py`'s fail-closed paths
already implement this discipline; this change extends it rather than inventing it. The new
`auroc_interval` lives in a **new module**, not `calibration.py`, so the TCB carve-out stays at
literally zero edits.

### 6. G3 is fixed in the TCB, in its own PR

`_upper_half_ci_width` returns `0.0` for "no data", vacuously clearing the `≤ 0.20` health
floor. Note the asymmetry: the identical `wilson_interval(0,0)` return is fail-**closed** at
`merge_gate._wilson_bound` and fail-**open** here. The fix is an additive sentinel constant;
direction is strictly fail-closed, so it can only flip `is_trustworthy` True→False and cannot
widen autonomy. It is latent today because zero `HUMAN_AUDIT` means no domain reaches the
health check at all.

## Consequences

**Positive:** an externally runnable artifact with no LLM, no server, and no telemetry; a
report that can say "this signal has not been shown to discriminate" with an interval to back
it; the first real path to `HUMAN_AUDIT` data, which is the actual gate blocker.

**Negative / accepted:** `agent_core` gains a subpackage that shells out to `gh` — no rule
forbids it (`detectors.py` already does) but no ADR contemplated it either, so it is recorded
here. The wedge needs one genuinely new module (the truth-side selector) before it has any
day-one output; it is not the zero-cost repackaging the prior proposal assumed.

**Explicitly not changed:** `merge_gate.decide()`, `tau`, thresholds, the ADR 0005 enablement
checklist, `audit_sampler` sampling/verdict logic, `calibration.py`, and the `config/*.yaml`
tunables. Auto-merge stays off.

**Reversibility:** the ingestion subpackage, HTML renderer, and discrimination module are
additive and deletable. The G3 fix is a one-line constant. Nothing in the gate's decision path
imports any of it, and the F-ID gate asserts that separation.
