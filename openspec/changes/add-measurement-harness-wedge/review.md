# Peer Review — "add-business-readiness-wedge" proposal (2026-07-26)

**Reviewed artifact:** a proposed OpenSpec change resequencing the externally-visible wedge — a
`merge_gate_report` CLI (claimed as F-039), a shadow-mode runner, licence/packaging work, and a
positioning surface — ahead of soak operations, behind a hygiene gate (claimed as F-037).
Supplied inline; never committed to this repo.

**Method:** read-only verification against the working tree at `3ea80b1` (branch
`claude/business-readiness-wedge-719moi`); full reads of `features.yaml`,
`agent-core/agent_core/{calibration,calibration_report,merge_gate,merge_gate_ci,outcome_store,proxy_eval,ppi}.py`,
`scripts/{agent_confidence,merge_gate_context,eval_protected_paths}.py`, ADRs 0005/0019/0023/0025,
`docs/plans/{agents-critical-path,real-data-activation,agent-record-decontamination}/`, and all
15 workflows; the live outcome store pulled from `refs/heads/merge-gate-data`; and independent
recomputation of the Wilson figures. Then adversarially re-reviewed by four independent agents
— refute-the-facts, refute-the-wedge, independent-design, and completeness — which corrected
four errors in the first pass. Those corrections are marked inline.

**Outcome:** the strategic instinct is adopted; the premise is replaced. Carried into
`proposal.md` + `design.md` + `tasks.md` in this directory.

---

## Verdict

Right instinct, wrong tree. Gate public work on hygiene, put one honest artifact in an
outsider's hands, refuse LLM calls on untrusted PR content, keep determinism, reuse the
calibration engine — all correct. But roughly half the change is already built, six factual
claims are false, and the headline positioning promises a number the system provably cannot
produce. What failed was verification against the tree, not judgment.

**This is the third pass over the same drift.** `docs/plans/agents-critical-path/REVIEW.md`
(July 2026) used this same method and already found the `merge_gate_report`-duplicates-
`store_sync stats` result (:30-35), the ADR-collision result (:19-21), and the `LabelSource`
enumeration (:22-28). The proposal repeats errors refuted twice before.

## Findings that change execution

**F-039 is not the reporting CLI — REFUTED.** `features.yaml:691` is "Public-surface
backwards-compat guard", `status: done`. The report is **F-043** and already ships a CLI
(`calibration_report.py:320`). `docs/plans/agents-critical-path/REVIEW.md:30` already rejected
a parallel `merge_gate_report` as duplicative.

**F-037 is not the credential scrub — REFUTED.** `features.yaml:653` is "Monorepo quality-floor
remediation", `status: done`. The scrub is Phase 0 of `docs/plans/agents-critical-path/PLAN.md`,
under an F-number never claimed.

**LICENSE and NOTICE already exist — REFUTED (task complete).** Present in all seven package
directories, with `license`/`license-files` wired in `pyproject.toml`. *But* `NOTICE:15-19`
groups the **Elastic Licence 2.0** `arize-phoenix-evals` extra with permissive ones.

**Shadow mode already exists — REFUTED.** `.github/workflows/calibrated-merge-gate.yml:75` runs
a log-only shadow job on every PR with `permissions: contents: read`. Auto-merge is
default-off (ADR 0005) behind a repo variable.

**Reserving `F-TBD-1/2` violates a documented convention — CONFIRMED.**
`openspec/project.md:34`: "F-numbers are claimed at land, never reserved in a proposal." All
four IDs the 2026-07-03 plan pre-assigned drifted. Next free is **F-048** — and
`origin/feat/F-040-soak-stats` still holds F-040 in flight, so it is not a free slot.

**`openspec validate --strict` cannot run — CONFIRMED.** No binary, no CI reference;
`docs/openspec-spike.md:70` says so. The real validator is `scripts/validate.py`.

**The `label_class`/"mechanical" schema does not exist — CONFIRMED; the conclusion drawn from
it was PARTIALLY TRUE.** The real schema is `label_source: str | None` against `LabelSource`.
The first pass called a type-level guarantee *unimplementable*; that overreached. ADR 0025's
tolerance covers unknown **fields**, not **values**. The correct objection is narrower: a
future fifth label source would harden into a parse error for older readers. A write-boundary
guard plus an AST absence proof is the right shape.

**The hygiene gate is real and unstarted — CONFIRMED.** The Langfuse pair is still unredacted
at `HARNESS_SPEC.md:311-312`, `docs/decisions/0003-langfuse-integration.md:7-8`,
`progress.md:280`, and **no workflow contains any secret-scanning step**. Two first-pass
overstatements corrected: `NEXT_STEPS.md:257` is *not* a false claim (it covers the dashboard
and `.env`, not the doc scrub), and `feat/F-038-gitleaks` is *not* "36k lines stale" — that was
a two-dot diff. It is 155 behind / 2 ahead, contributing 10 files / +229 / −5, and merges with
exactly **5 conflicts**.

## The finding that replaces the premise

The wedge sells "calibrated confidence." Four facts say it cannot be delivered:

1. `raw_confidence` is a diff-shape heuristic, not agent belief
   (`scripts/agent_confidence.py:11-14`, ADR 0023 §1).
2. ADR 0023 §1 puts its honest expectation at **AUROC ≈ 0.5–0.65**, against a `min_auroc` floor
   of **0.65** (`merge_gate.py:49`). The only shipped confidence signal is predicted, in
   writing, to fail the system's own health gate.
3. The live store holds **46 records, zero `human_audit`**; all 8 agent-domain rows are
   entirely unlabelled, and 6 of 8 sit at exactly `clamp_lo`. `tau` is undefined everywhere.
4. The four-gate Wilson stack needs ~378 all-correct audits (recomputed: n ≥ 189 held-out;
   the design doc's 188 fails at 0.979975), plus ≥35/bin, `bin_ci_width ≤ 0.20`, `n ≥ 200`.

Two corrections to the first pass: "cannot" overstates on the arithmetic — ~380 is *policy*
(`risk_target`), and at 0.05 the bar is ~146. The conclusion survives on **G1** instead:
`GatePolicyConfig` is unreachable from any config or CLI, so a partner has no knob. And
"AUROC ≈ coin-flip" is a documented *expectation*, not a measurement — no AUROC has ever been
computed here on real audit data.

**The honest wedge is the measurement harness** (see `proposal.md`). One correction that
changes its cost: it is **not** zero-audit. `proxy_eval.build_dataset:150-157` admits pairs
only when `label_source == HUMAN_AUDIT`, so at zero audits every slice reads "insufficient
pairs: n=0 < 3". A truth-side selector is required. And **no AUROC confidence interval exists
anywhere in the repo** — `calibration.auroc:163` returns a bare float — so the "honest
uncertainty" claim needs new math before it is true.

## Blockers neither the proposal nor the first pass caught

- **`SECURITY.md:53` asserts "Secret scanning runs in CI."** It does not. `:49-51` asserts Snyk
  monitors dependencies; no workflow references it. Publishing a security policy that overstates
  the very control this change adds is the worst available optic.
- **CHARTER §3 scope expansion** past *"not an autonomous merge bot… not a general observability
  platform"*, requiring a Ratified Amendments entry and GOVERNANCE sign-off. Also, CHARTER §1
  delegates the vision statement to the README, so rewriting the README opening silently amends
  the charter — and `check_charter_drift.py` cannot detect it.
- **Trademark.** `langfuse-eval-harness` and `claude-foundation-tools` are third-party marks;
  Apache-2.0 §6 grants no trademark licence. All candidates are unclaimed on PyPI.
- **`.gitignore:62` is `*.html`.** A committed sample report and every HTML fixture would be
  silently untracked.
- **`pipx install` cannot deliver this.** The root distribution excludes `agent-core`
  (`packages.find where = ["src"]`), `agent-core` declares no `[project.scripts]`, there is no
  publish workflow, and `git tag` returns zero.
- **`store_sync` defaults would publish a partner's records into this repo** (`origin` /
  `merge-gate-data`). The leaky field is `domain`, which encodes module taxonomy.
- **Against an external repo the classifier degrades to all-zeros.**
  `config/agent-authors.yaml:17` knows only `claude/`; a partner on Copilot/Devin/Cursor routes
  every PR to the human lane at `0.0`.
- **Every test file is `[P]`** (`scripts/eval_protected_paths.py:29-46` covers every sibling
  `tests/**`), so strict per-PR protected isolation lands agent-core below its 95% floor.
- **G3 is a TCB fix, not a report fix** — `_upper_half_ci_width` (`outcome_store.py:180`) feeds
  the gate's health, not the renderer. Its trigger is exactly today's data shape.

Clean: no vendored third-party source; no `pull_request_target`; no secret exposed to a
PR-triggered workflow; no PR titles, bodies, or diffs persisted in the record schema.

## Claims confirmed accurate

Hygiene-first sequencing; reuse the calibration engine rather than reimplementing it (all of
`wilson_interval`, `expected_calibration_error`, `brier_decomposition`, `auroc`,
`selective_risk_coverage`, `IsotonicCalibrator` exist behind a `Calibrator` Protocol); the
no-LLM, determinism, and untrusted-input constraints; keeping discovery calls out of the spec.
