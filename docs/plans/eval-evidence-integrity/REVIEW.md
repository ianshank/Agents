# Peer Review — Eval-Tool Test Matrix Readiness Brief

**Reviewed tree:** `9eb0520` (clean, branch `claude/eval-tools-test-matrix-80uq1c`)
**Under review:** an eval-tool test-matrix readiness brief prepared for a VP of Software
Quality Engineering and a Sr Director of Architecture, written earlier in the same session
that produced this review.
**Protocol:** the repo's own `skills/openspec-peer-review` two-pass method — Pass 1 mechanical
fact-check (CONFIRMED / CORRECTED / REFUTED, evidence required), Pass 2 adversarial design
review (refuted attacks recorded, never deleted).

## Verdict

The reviewed brief's headline recommendation — widen the M8 composability axis to all 41
registered components as Phase 1 — is withdrawn on adversarial review (A2 below): the
mechanism it would widen counts config presence, not execution, and already contains a
provably vacuous cell. Two findings not in the original brief displace its framing entirely:
`main` carries no branch protection, so every gate in the repository is advisory at the merge
boundary (P1.4), and a real integrity hole exists in judge-gating authorisation that the
brief never surfaced (P1.10). The rewritten plan in `./PLAN.md` reorders the work around
*enforcement before evidence, semantics before scale*.

---

## Pass 1 — mechanical fact-check

### P1.1 · "M8 covers 17 of 41 components" — CORRECTED twice; the honest number is 20 of 41 never composed

Two errors in opposite directions. The artifact's own "kinds exercised" table
(`docs/matrix-coverage.md`) sums to **18**, not 17. But three of the 23 it omits are
**already engine-composed in tests that run inside the coverage gate**: `csv` and `parquet`
(`tests/integration/test_pipeline_e2e.py:110`, `:153`, both re-run and passing) and the
`langfuse` sink (`tests/test_engine.py:36` through `NullLangfuseClient`).

Defensible statement: **20 of 41 registered components have never been run through
`EvalEngine` anywhere in the repository** — datasets `jsonl`, `langfuse`, `braintrust`;
judges `openai`, `anthropic`, `bedrock`, `phoenix_evals`, `panel`; scorers `autoevals`,
`json_keys`, `policy_violation`, `regex_match`, `state_transition`; sinks `html_file`,
`phoenix`, `braintrust`; adapters `filesystem`, `sqlite`, `mock_http`; target `model`. For
the other three the gap is matrix *accounting*, not testing.

### P1.2 · The M8 mechanism does not measure what the brief assumed — REFUTED premise

M8 is not a per-component dimension. `REQUIRED_DIMS` (`tests/_matrix_coverage.py:65-75`)
holds only dims 1,2,3,5,6; M8 lives in `EXTRA_SUITES` as `{"engine": {8}}` and is discharged
by a per-kind non-emptiness assert (`tests/test_matrix_coverage.py:91-95`). `pipeline_kinds()`
(`tests/_matrix_coverage.py:744-771`) credits a component by **reading a validated config
dict**. Every other dimension counts AST `test_m<dim>_*` methods; M8 alone counts appearing
in a dict.

Demonstrated, not theorised: pipeline `echo_exact_match` declares `judge: {type: mock}` and
is credited, but its scorers are `exact_match` and `contains`, neither judge-backed —
instrumented, `MockJudge.evaluate` is called **zero times**. **The matrix already contains a
vacuous M8 cell.**

### P1.3 · "129 of 183 cells hold one test" — CORRECTED as analytically misleading

True arithmetic, wrong argument.

| Dim | Cells | Tests | Exactly 1 |
|---|---|---|---|
| M1 Correctness | 41 | 87 | 15 |
| M2 Edge Cases | 41 | 90 | 23 |
| M3 Type Safety | 38 | 39 | 37 |
| M5 Determinism | 25 | 25 | 25 |
| M6 Error Handling | 38 | 51 | 29 |

M3 and M5 are **single-assertion dimensions by nature** and contribute 62 of the 129. The
defensible finding is narrower: **M6 has one error-handling test for 29 of 38 components and
M2 one edge case for 23 of 41** — dimensions whose names are plural and whose evidence is
singular.

### P1.4 · `main` has no branch protection — VERIFIED LIVE; the headline

Every branch including `main` reports `"protected": false` today (GitHub API, 2026-09-02).
Consequences, all mechanical: no CI job is a required check; CODEOWNERS review is
unenforceable without protection; `scripts/check_protected_changes.py` accepts an
`--approved` force flag and `.github/**` is guarded only by that same non-required job; ADR
0005's enablement checklist still carries this as an **unchecked** box. `merge-gate-data`
must stay unprotected or `store_sync push` breaks.

### P1.5 · "Gates never run live evaluations blocks live CI" — REFUTED

A §3 non-goal bullet (`docs/CHARTER.md:62-63`) scoped by its own next sentence to one gate:
"The regression gate is diff-only." `docs/decisions/0021-ci-gate-delegation.md:33`
**explicitly sanctions** "Scheduled, dispatch-only, or system-level workflows".
`phoenix-live.yml` is the working precedent. No charter amendment is needed; new workflows
do need the `eval-change-approved` label. Also corrected: §6 contains no amendment procedure
— that is two lines in `GOVERNANCE.md:51-52`; nine Ratified Amendments exist.

### P1.6 · "6 of 7 gate scripts lack `--cov-config`" — CORRECTED to 7 of 7

All seven generated `do_coverage()` bodies omit it. Root's `--cov-config` sits at
`scripts/quality-gate.sh:78` inside `do_extra()` — a different stage, which is where
`NEXT_STEPS.md`'s count mis-derives. The generator never emits it
(`skills/quality-gate/scripts/gategen/render.py`). `COVERAGE_RCFILE` appears **zero times
repo-wide**; the guarded set is closed at
`("COVERAGE_SOURCE","COV_FAIL_UNDER","PYTEST_ADDOPTS")`.

### P1.7 · "`docs.yml` hardcodes 5 registries and skips `STATE_ADAPTERS`" — REFUTED

A stale `NEXT_STEPS.md` claim repeated in the brief without re-derivation. The step invokes
`scripts/extract_registries.py --check`; the list is **AST-derived**, finds all **six**
registries including `STATE_ADAPTERS`, and both READMEs document its four adapters. F-058
closed this. Residual, narrower: `check_docs_drift` `continue`s when a doc section heading
is absent, so renaming a README section silently disables that registry's drift check, and
the job is `continue-on-error` besides.

### P1.8 · The protected-path threat model is inverted — new finding

`skills/quality-gate/scripts/gategen/render.py` generates *every* coverage gate in the
monorepo and is in neither `PROTECTED_PATTERNS` nor CODEOWNERS. Adding one test method to
`tests/test_matrix_eval_tools.py` needs a label and Code-Owner review; rewriting the
generator that emits all seven coverage floors needs neither.

### P1.9 · The e2e artifact regressed under a provenance stamp that cannot be true — new, worse than "stale"

- The runner has **not changed** since the render (0 commits; last touched Aug 9, ten days
  before the stamp). All 40 declared rows re-derive byte-identically. Declared columns are
  correct.
- Commit `3272006` (Aug 20) **replaced a 1627-test / 38-observed render with a
  995-test / 30-observed one** — Tier D went 7 SKIP to 7 NOT-RUN. Evidence quality moved
  backwards.
- It stamps SHA `09337aec`, but the file **at** `09337aec` stamps `e899249a`, a different
  date and a different host. The artifact cannot be a render of the commit it names.
- Actual `suite:root` today is **1993**, not 995; `agent-core` 876, not 714.
- The freshness gate structurally cannot catch this: ADR 0033 §3 excludes Provenance from
  comparison, for a defensible reason, and the gate never runs in CI anyway.

### P1.10 · Judge-gating authorisation is exported, tested, and never called — new, highest-severity integrity finding

Three links; only the weakest is connected. (1) A gating config must name a calibration
artifact — enforced at `cli.py:84`, but it checks only `judge_calibration is not None`, so
any non-empty string passes. (2) That artifact must authorise gating —
`require_report_to_gate` (`agent_core_adapter/gate_authorization.py:27-47`) enforces
`may_gate`, artifact-ID match and names `failing_checks`; it is exported, in `__all__`,
unit-tested, and has **zero runtime callers**. (3) That authorisation must rest on real
measurement — impossible; see P1.11.

**Net: a release can be gated on an LLM judge today by writing
`calibration_artifact_id: "anything"`.**

### P1.11 · The judge-validity machinery has no fuel — CONFIRMED; a data problem, not plumbing

`agent_core/golden.py` and `pairwise.py` ship complete and guarded — hash-stable splits,
`evaluate_on_split` enforcing held-out discipline in code, `cohen_kappa`,
`percent_agreement`, construction-validated canary kinds. There are **zero committed
`GoldenSet` or `PairwiseSet` instances and zero human-labeled rows anywhere**. Every corpus
is synthetic or a test fixture. The merge-gate store holds zero `HUMAN_AUDIT` rows.

### P1.12 · The fleet mechanism does not exist for 3 of 5 packages — REFUTES ADR 0032 §6

| Package | Registry-like structure | Components |
|---|---|---|
| flow-corpus | real `Registry` (`specimens/base.py:23`) | 3 |
| agent-core | `CALIBRATOR_FACTORIES` (`recalibration.py:112`) | 2 |
| behavioral-regression | none (empty `MIGRATIONS`) | — |
| flow-protocol | none (empty `MIGRATIONS`) | — |
| claude-foundation | none; hooks found by filesystem + `settings.json` | — |

`agent-core` also holds a false friend: `CalibratorRegistry` (`recalibration.py:126`) is a
per-domain fitted-model container, not a name-to-implementation registry. The skills layer,
by contrast, transfers cleanly — `skills-ci.yml:483-521` already runs a derived census with
an `EXEMPT` waiver map, a staleness re-check and an empty-census refusal, guarded by F-050.

### P1.13 · Two claims in the original brief the tree does not support — REFUTED

- **`TestCoverageGrid` does not exist.** Cited as an existing join between the two matrices.
  It returns nothing repo-wide. There is no mechanism joining them; the only link is a
  comment noting the architectural parallel (`tests/_e2e_matrix.py:3`).
- **"Integration tests are skipped by default" is stale**, in `AGENTS.md:146`.
  `testpaths = ["tests"]` with no `-m "not integration"` means `tests/integration/` is
  collected by the coverage gate; only credential-fixture tests skip.

### P1.14 · New defect — the plans index is unguarded and already stale

`docs/README.md` declares "Every plan is listed here — an unlisted plan is unreachable from
any documented entry point, which is how eleven of them went invisible before this index
existed." Seven plan directories existed at the time of this review; six were listed.
`docs/plans/orbital-drift-alignment/` was not. No CI guard exists, while the structurally
identical OpenSpec change-index guard sits ~50 lines away in `docs.yml`. Fixed in the same
change that adds this document — see `./PLAN.md` Phase 0.

### P1.15 · No mutation tooling exists — CONFIRMED

No `mutmut` / `cosmic-ray` in `pyproject.toml`, `Makefile` or any workflow. Mutation testing
is manual, recorded as prose canaries in `progress.md`. Vacuity refusal exists at census
level only, never at cell level — and the repo has been burned at cell level twice (three
phoenix cells asserting nothing; F-061's three surviving mutants after full coverage).

### P1.16 · Effort estimates in the original brief — withdrawn

Day/week ranges were attached to five phases with no basis. Removed. Work is sequenced by
dependency and by the decision each phase forces; sizing belongs to whoever staffs it.

---

## Pass 2 — adversarial design review

Attacks verified before being kept; refuted attacks retained.

### A1 · "Enable branch protection with Code-Owner review" — CONFIRMED UNIMPLEMENTABLE

The obvious fix for P1.4 does not work, and this is why it was never done. There is exactly
one collaborator, `ianshank` (admin), and CODEOWNERS maps all 15 protected paths to them.
GitHub forbids self-approval, so "Require review from Code Owners" makes **every PR
permanently unmergeable**. The eval-integrity design is two-layer by intent, and one layer
structurally requires a reviewer population of two or more that the project does not have.

### A2 · "Make M8 a per-component floor" (the original brief's Phase 1) — WITHDRAWN

Because `pipeline_kinds()` credits config presence, a 41-cell floor is 41 cells satisfiable
without exercising anything. Two cells would be actively harmful: `OpenAIJudge` and
`AnthropicJudge` construct real clients in `__init__` with no `client=` seam, so a pipeline
naming `openai` beside an `llm_judge` scorer attempts real network egress from CI and still
goes green — the engine swallows the connection error into a `0.0` score with a comment
(verified by execution). `bedrock` and `phoenix_evals` cannot construct at all in that job.

### A3 · "Add a second test to thin cells" — CONFIRMED Goodhart trap; withdrawn

Driving a count from 1 to 2 optimises the artifact, not the evidence — the failure
`scripts/fix_loop.py` exists to name. The instrument is a negative control per cell, and
P1.3 narrows where it is even warranted (M6, M2).

### A4 · "An evidence ledger joining the artifacts" — CONFIRMED risk; mitigation required

The diagnosed problem is un-joined generated artifacts; a fourth is the same defect with a
larger denominator. Any join must derive entirely from existing generators, restate no step
list, floor or component name, and be freshness-gated by the same mechanism as its inputs.

### A5 · "Scheduled live workflows are flaky and expensive" — REFUTED as a blocker, kept as a constraint

The repo already solved the false-green problem: `scripts/smokes/_smoke_lib.py` fixes
`SKIP_EXIT_CODE = 78` (EX_CONFIG, deliberately not 2), plus `missing_env`, `redact`,
`safe_endpoint`, `use_os_trust_store`. Both existing smokes needed two iterations to become
non-vacuous. Constraint retained: a new smoke must assert a real round-trip, not a
constructor call.

### A6 · "Extend to the fleet as ADR 0032 promised" — CONFIRMED trap; mitigated, not avoided

Executing it as written hand-declares axes for three registry-less packages, reintroducing
the manual-list defect class F-050/F-052/F-053 closed. The mitigation (Phase 9 in
`./PLAN.md`) cross-checks hand-declared axes against each package's frozen public-surface
baseline, meeting ADR 0032 rule 2's own "checked declaration" standard rather than
reintroducing the defect.

### A7 · "The freshness gate protects the e2e artifact" — REFUTED

ADR 0033 §3's Provenance exclusion is sound in isolation, but combined with the gate never
running in CI it let the artifact both regress and mis-stamp itself. The fix is not to gate
the SHA equal to HEAD — that failure mode is real — but to gate it reachable and consistent:
the stamped SHA exists, is an ancestor of HEAD, and re-rendering at that SHA reproduces the
committed body. Plus a monotonicity check, since the Aug-20 downgrade was silent.

### A8 · "Port the runner to POSIX" — CONFIRMED necessary, not as a transliteration

Only 9 of 40 steps are table-declared; 31 are imperative with inline fixture setup across
674 lines. Convert the 31 to the existing hashtable shape first — behaviour-preserving, and
it collapses the six-regex parser (`tests/_e2e_matrix.py:333-364`) instead of duplicating it
into a second driver.

---

See `./PLAN.md` for the rewritten plan this review produced.
