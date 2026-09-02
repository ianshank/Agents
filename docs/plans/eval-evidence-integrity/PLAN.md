# Implementation Plan — Eval Evidence Integrity

**ID:** PLAN-2026-09-02-eval-evidence-integrity
**Date:** 2026-09-02 · **Base commit:** `9eb0520`
**Motivated by:** `./REVIEW.md` — peer review of an eval-tool test-matrix readiness brief.
The brief's headline recommendation (widen M8 composability to all 41 registered components)
is withdrawn: the mechanism it would widen credits config presence, not execution, and
already contains a provably vacuous cell. Two findings not in the original brief displace its
framing — `main` carries no branch protection, and judge-gating authorisation is exported,
tested, and never called in production.
**Scope:** make the repository's eval gates load-bearing, make the M8 composability axis mean
execution rather than config presence, widen it honestly across all 41 registered components,
close the judge-gating authorisation gap, repair the e2e matrix's provenance integrity, and
extend the matrix convention to the five sibling packages.
**Non-goals:** a mutation-testing harness (none exists; out of scope for this plan);
human-labelling infrastructure beyond the first committed corpus (Phase 7 states the labelling
work itself as an open, owned gap rather than attempting to automate it); enabling
Code-Owner review on `main` (structurally impossible with one collaborator, see Pass 2 A1);
`bedrock` and `phoenix_evals` M8 cells (deferred with named reasons — a CI install-line
decision and an unresolved `pyarrow` pin conflict, respectively).

---

## Cross-cutting standards

| Standard | Rule | Source of truth |
|---|---|---|
| Organising principle | Enforcement before evidence, semantics before scale. No phase widens a measurement's coverage before an earlier phase has fixed what that measurement means | `./REVIEW.md` Pass 2 A2 |
| Protected paths | Touching `tests/**`, `.github/**`, `scripts/validations/**`, `features.yaml`, `config/**`, `src/eval_harness/{gating,scorers,judges}/`, or `architecture.yaml` needs the `eval-change-approved` label + CODEOWNERS review | `scripts/eval_protected_paths.py` |
| F-IDs / ADR numbers | Claimed **at land**, never reserved in a proposal | `openspec/project.md:34` |
| Generated artifacts | Never hand-edited; regenerated via each artifact's own `--update`, freshness-gated by its own `--check` | ADR 0032, ADR 0033 |
| Vacuity refusal | A measurement that can report a pass having measured nothing must be refused, not merely documented | ADR 0029; `tests/_matrix_coverage.py` census-level precedent |
| Coverage floors | root/`eval_harness` 96; `agent-core`/`behavioral-regression`/`flow-corpus`/`flow-protocol` 95; `claude-foundation`/`scripts` 85; skills 95 (99 `dataset-lint`) | per-package `pyproject.toml`; `scripts/.coveragerc` |
| Backwards compatibility | Public-surface changes (Phase 4's `client=` seams) regenerate `tests/public_surface_baseline.json` in the same protected PR — never split across an unprotected/protected boundary | F-039 |

## Decision points (defaults applied this round)

1. **Deliverable** — house artifacts (`docs/plans/eval-evidence-integrity/`, OpenSpec change
   packages) plus a draft PR on the designated branch.
2. **Fleet scope (Phase 9)** — all five sibling packages, hand-declaring component axes where
   no registry exists, mitigated by cross-checking each hand declaration against the
   package's frozen public-surface baseline rather than leaving it a bare, unchecked list.
3. **Judge DI seam (Phase 4)** — in scope, as a protected-path production change with its own
   ADR, mirroring `ModelTarget`'s existing seam.

---

## Phase 0 — Publish the honest baseline

Disclosure precedes every fix, because the delta only means something if the starting number
was published first. All unprotected paths, mergeable immediately.

- `docs/plans/eval-evidence-integrity/{PLAN.md,REVIEW.md}` (this document and its review),
  plus rows in `docs/README.md`'s Plans table for both this topic and the pre-existing
  unlisted `orbital-drift-alignment` topic.
- `docs/e2e-matrix/ERRATA.md` recording the `3272006` provenance defect and the 1627-to-995
  test-count regression, linked from the artifact's Provenance section.
- Doc corrections: `AGENTS.md`'s stale integration-marker claim; `docs/roadmap/epic-1-*.md`'s
  "PR #163 open" (merged); `NEXT_STEPS.md`'s "6 of 7" `--cov-config` count and its
  already-fixed registry-drift item; the two landed OpenSpec changes
  (`add-panel-judge`, `add-stateful-outcome-evaluation`) still marked "proposed" in
  `openspec/README.md`.

**Yields:** one document stating the real number — 20 of 41 components never engine-composed
— before any improvement is claimed.

## Phase 1 — Make the existing gates load-bearing

**Decision forced:** which checks become required, given Code-Owner review is impossible.

- Repo settings on `main` (owner action, not a code change in this PR): required status
  checks only — `quality-gates`, `eval-harness-ci`, the four package CIs, `architecture-drift`.
  Do **not** enable Code-Owner review (Pass 2 A1). Leave `merge-gate-data` unprotected
  (ADR 0018). Decide and record the admin-bypass posture honestly.
- New ADR — branch protection under a single maintainer: what is enabled, why Code-Owner
  review is deferred with the self-approval deadlock as the reason and a second reviewer as
  the unblock condition, and that `--approved` remains an explicit, logged override. Replaces
  ADR 0005's silently-unchecked enablement box.
- Extend `scripts/check_guard_reachability.py` (or add a sibling) to assert each protected
  pattern's guard job is in the required-checks list, not merely that it fires.
- `skills/quality-gate/scripts/gategen/render.py`: emit `--cov-config` in `_coverage_command`
  and scrub `COVERAGE_RCFILE` beside `PYTEST_ADDOPTS`; regenerate all seven `quality-gate.sh`
  files; extend `_GUARDED_VARS` in `skills/quality-gate/tests/test_coverage_gate_integrity.py`.
  Closes P1.6/P1.8.

**Risk to manage:** run each candidate check about five times on `main` before requiring it.
Requiring a flaky check with one maintainer and no bypass is a self-inflicted outage.

## Phase 2 — Make an M8 cell mean execution

The load-bearing phase. Nothing after it is safe to build first.

- New `tests/_m8_probe.py` (underscore precedent: `_matrix_coverage.py`, `_e2e_matrix.py`). A
  context manager patching `Registry.create` — the single construction choke point for all
  six kinds, so `panel`'s members and `weighted`'s children are credited automatically —
  wrapping each instance's protocol method with a counter keyed
  `(kind, canonical_name, method)`. Protocol method names are a checked declaration
  cross-checked at import against the six Protocols in `core/interfaces.py`, so a rename
  fails loudly.
- `_assert_no_swallowed_errors(result)`: no `ItemResult` is an exception, and no
  `ScoreResult.comment` starts with `"scorer error: "` — the exact swallow marker at
  `engine.py:224-231`. This is what catches the openai-egress-goes-green case.
- Session-scoped egress guard patching `socket.socket.connect` to raise for non-loopback,
  scoped to the matrix suite by marker first (widening it repo-wide is separate scope).
- Add one execution assertion per existing M8 test. `echo_exact_match` is expected to fail —
  that failure, visible in the commit history, is the phase's headline evidence that the
  mechanism can falsify.
- `tests/_matrix_coverage.py`: add `pipeline_execution_census()` beside `pipeline_kinds()`.
  Keep `pipeline_kinds()` and publish *declared minus executed* as the vacuity metric.
- Cell-level vacuity refusal mirroring the existing census-level test.
- New "engine execution" section in `docs/matrix-coverage.md` via a new
  `_render_execution_section` — components by {invoked / declared-only / absent}.

**Deliberately not done:** M8 does not enter `REQUIRED_DIMS`. It measures a different thing
(did it run) from M1/M2/M3/M5/M6 (how many test methods); forcing it into `_GRID_DIMS` needs
a non-count branch in `_render_kind_section`, collides with `_collect_cells`'s refusal of
`MATRIX_COMPONENTS` on extra suites, and would require an ADR 0032 amendment for no gain.

## Phase 3 — Breadth: the 19 test-only components

- Generalise `_run`'s tmp-path override (`json_file`-only today) into a table keyed by
  `(kind, type)`.
- `PIPELINES` values become zero-arg factories, removing the `copy.deepcopy` and allowing an
  injected stub for `model`. Verify first that no AST path reads `PIPELINES` as a literal —
  the extractor supports single-file constant folding, and factories would be opaque to it.
- Cheapest first: `phoenix` and `braintrust` sinks asserting through
  `NullPhoenixScoreClient.scores` and `NullBrainTrustClient.items` (both default
  `enabled=False` into recording nulls, zero config); `panel` over `{"type":"mock"}` members;
  `langfuse`/`braintrust` datasets via `NullLangfuseClient(dataset_items=...)` and the
  existing `fake_braintrust` fixture; then `sqlite` (`:memory:`), `filesystem` (tmp root),
  `mock_http`, `html_file`, `jsonl`.
- Credit `csv`, `parquet` and the `langfuse` sink by adding them to `PIPELINES`, keeping the
  ledger single-sourced rather than counted from outside tests.

## Phase 4 — DI seams for the two network judges

Add `client: Any | None = None` to `OpenAIJudge.__init__` (`judges/__init__.py:101-122`) and
`AnthropicJudge.__init__` (`:250-265`), mirroring `ModelTarget`'s documented seam exactly,
moving the SDK import inside the `client is None` branch. Its own ADR. Regenerate
`tests/public_surface_baseline.json` in the same protected PR (a protected path, so this
phase cannot be split unprotected-first). The F-ID proof asserts constructing each judge with
an injected client performs zero socket connects.

**Deferred with reasons, not silently:** `bedrock` (needs a CI install-line decision) and
`phoenix_evals` (no `_EXTRA_PROVIDES` row; its pandas/numpy footprint versus the
`pyarrow>=14,<20` pin is unresolved — let `phoenix-live.yml`'s existing `dep-resolve` job
report first).

## Phase 5 — Live-provider evidence

No charter amendment needed (P1.5). Provider smokes on `_smoke_lib` — `anthropic`,
`bedrock`, `openai`, and a `model_target` smoke. Per-provider non-vacuity is the only new
design work: Anthropic has no `auth_check()`, so the honest analogue is a one-token
`messages.create` asserting response content. A scheduled, secret-gated `live-smokes.yml`
modelled on `phoenix-live.yml`. `derive_live_credentials` parses gates from runner source, so
the e2e matrix picks the steps up with no schema change.

## Phase 6 — Close the judge-gating authorisation hole

Change `require_calibration_for_judge_gating` (`gating/__init__.py:19`) to load the
referenced report and delegate to `require_report_to_gate`, and wire it at `cli.py:84`.
Regression test: `calibration_artifact_id: "anything"` must now be refused.

**Behaviour-breaking:** inventory every committed config and downstream consumer before
writing the proposal; if a real gate depends on the loose behaviour, this becomes a
two-release deprecation, not a one-PR fix.

## Phase 7 — Golden/pairwise corpus

The plan's only unbounded-latency item, and the true critical path for judge validity. Define
the labelling protocol (who labels, adjudication, target kappa), commit a first `GoldenSet`
(around 50 items) with real human labels, and assert in CI that a gating config references a
report whose corpus is non-synthetic. State explicitly in this document that judge validity
remains an open gap with an owner and a target date, separate from judge plumbing, which
Phase 6 closes.

## Phase 8 — E2E matrix integrity and a POSIX driver

- Provenance gated as reachable and consistent (Pass 2 A7), landed as an ADR 0033 amendment
  so the original exemption's reasoning survives and only its scope narrows.
- Monotonicity check: a render dropping observed steps or test counts fails or carries an
  explicit waiver row.
- Table-shape the 31 imperative runner steps first, then write `scripts/run_all_e2e.sh`
  against the same tables, then restore the nightly freshness step removed 2026-08-23.
- Unify the split behaviour where the CLI exits 2 and the pytest test skips.

## Phase 9 — Fleet extension, all five packages

- Derived where possible: flow-corpus from its `Registry`; agent-core from
  `CALIBRATOR_FACTORIES`, explicitly excluding the `CalibratorRegistry` false friend with a
  comment explaining why.
- Checked declaration where derivation is impossible — behavioral-regression,
  flow-protocol, claude-foundation. Cross-check every declared component against the frozen
  public-surface baseline each package already ships (`tests/public_surface_baseline.json`;
  claude-foundation uses `backwards_compat_baseline.json`). A declared component that is not
  an exported public name fails; a surface change makes the declaration go stale loudly.
  Amend ADR 0032 §6 to describe the two mechanisms rather than claiming one.
- Skills layer: reuse the shipped census idiom, but first collapse the `EXEMPT` list
  currently hard-coded in three places into one importable source.
- Pre-flight inventory from `add-eval-matrix-completeness/review.md:79`: re-derive the "at
  least 2 cases per Schema-A eval file" and grader-union counts — both original figures may
  be stale.

## Phase 10 — Depth: canaries, not counts

Scoped by P1.3 to M6 and M2 only; M3 and M5 are excluded as single-assertion by nature. The
instrument is a negative control per floor cell, not a larger test count. No mutation-testing
harness in this plan.

---

## Packaging

| Artifact | Contents |
|---|---|
| `docs/plans/eval-evidence-integrity/{PLAN.md,REVIEW.md}` + `docs/README.md` rows | This plan and its review |
| `docs/e2e-matrix/ERRATA.md` | The `3272006` provenance defect |
| New ADR — branch protection under a single maintainer | Phase 1 |
| OpenSpec `prove-m8-execution` | Phases 2-4 |
| OpenSpec `enforce-judge-gate-authorization` | Phase 6 |
| OpenSpec `repair-e2e-matrix-provenance` | Phase 8, carrying the ADR 0033 amendment |
| OpenSpec `extend-matrix-to-fleet` | Phase 9, carrying the ADR 0032 §6 amendment |
| New ADR — judge `client=` DI seam | Phase 4 |

Each OpenSpec change needs a bullet in `openspec/README.md`'s "Current changes" — that index
is CI-guarded. F-IDs and ADR numbers are claimed at land, never reserved.

## PR decomposition, Phases 0-2

1. **PR 1 (unprotected)** — plan, review, errata, `docs/README.md` rows, the
   `prove-m8-execution` change directory and its index bullet. Mergeable immediately.
2. **PR 2 (unprotected)** — the branch-protection ADR and the gate-generator
   `--cov-config` / `COVERAGE_RCFILE` fix. Repo settings changed out-of-band, recorded in the
   PR body. Any `check_guard_reachability` change splits into PR 2b (protected).
3. **PR 3 (protected)** — `tests/_m8_probe.py` and the egress guard only. No policy change,
   no new assertions on existing tests, so it reviews as pure machinery.
4. **PR 4 (protected)** — turn the ledger on, fix the vacuous cell, add the execution census
   and renderer, regenerate the artifact. Show the intermediate red commit where
   `echo_exact_match` fails.
5. **PR 5 (protected)** — `features.yaml` F-ID and its `F_0NN.py` proof that a pipeline
   declaring a component it never invokes is rejected.

## Verification

```bash
make check-all                                        # root + 5 packages at their floors
make pre-pr                                           # every gate CI enforces, accumulated
python -m pytest tests/test_matrix_eval_tools.py tests/test_matrix_coverage.py -q
python tests/test_matrix_coverage.py --check          # freshness
python -m pytest tests/test_public_surface.py -q
python tests/test_public_surface.py --update
python scripts/check_guard_reachability.py --json
python scripts/validations/F_057.py                   # judge-calibration proof
python -m pytest tests/test_e2e_matrix.py -q
python scripts/validate.py --tier fast --strict-git
make determinism
```

Per-phase acceptance is behavioural: reverting each new execution assertion must fail a named
test (the repo's "canaries recorded" convention), and `--update` must refuse to write a holed
matrix or a downgraded e2e render.

## What this plan does not do, and why

- **Enable Code-Owner review** to "turn on enforcement" — it bricks the repo at one
  collaborator (Pass 2 A1).
- **Promote M8 into `REQUIRED_DIMS`** — 41 green cells from config parsing, plus renderer and
  ADR churn for no gain.
- **Delete `pipeline_kinds()`** — keeping it is what lets the vacuity delta be published.
- **Gate the e2e Provenance SHA equal to HEAD** — permanently red on the carrying commit.
- **Chase `phoenix_evals` into the offline job** before the pyarrow/pandas question is
  settled.
- **Add a fourth copy of the skills `EXEMPT` list.**
- **Build mutation tooling in this plan.**
- **Improve M3/M5 single-test cells** — padding a metric a reader will read as padding.
- **Silently re-render the e2e matrix** — errata first, fix second.
- **Treat Phase 7 labelling as engineering** — no CI work substitutes for labeled rows.

## Sequencing risks

- Phase 4 touches `judges/`, the most-protected path, and gates two cells. If the label is
  slow, land Phase 3 and waive those two cells temporarily rather than block the phase.
- Phase 1's protection should be enabled after Phase 0's drift fixes merge, or the fixes
  queue behind the checks they repair.
- Phase 9 depends on Phase 2's semantics, not merely Phase 3 — extending under
  config-presence M8 exports the vacuity fleet-wide.
- Phases 2 and 8 both touch generated-artifact freshness; serialise them or a regeneration in
  one reads as staleness in the other's diff.

## Delivery order

Phase 0 -> Phase 1 -> Phase 2 -> Phase 3 -> Phase 4 -> Phase 5 (independent of 6-10) ->
Phase 6 -> Phase 7 (long-lead, start the labelling protocol document in parallel with
Phase 2) -> Phase 8 (independent of 3-7; needs only Phase 0's errata) -> Phase 9 (needs
Phase 2's semantics) -> Phase 10.
