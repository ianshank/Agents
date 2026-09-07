# Gap analysis — requirements-eval branch peer review (2026-09-07)

Objective review of `cursor/requirements-eval-matrix-c319` (F-068, ADR 0047) against
`origin/main`, plus the tech debt and wiring gaps the review surfaced. Written after the
feature was complete and every gate was green, which is the point: **the gates were green
while the shipped feature did not run.**

Scope: the branch diff, the gate configuration it lands under, and the hooks/loops that
were supposed to catch what it got wrong. Findings are ordered by what they cost, not by
how hard they were to find.

---

## 1. The finding that matters

`eval-harness run --config config/requirements_eval.yaml` — the command
`config/README.md`, `AGENTS.md` and `CHANGELOG.md` all document — raised
`KeyError: "evidence source 'src-req-00-a' is not in the store"` on its first item.

The config declared `store_contents: {}`. Every one of the 25 corpus items declares two
evidence sources. The provenance wrapper fetches each declared source before running the
inner target, so the run died at item one, every time.

**Why every gate passed anyway.** The whole verification surface for this feature was
component-level: 111 unit tests constructing scorers and targets directly, a matrix
obligation satisfied by rows that build their own fixtures, and a validator (`F_068.py`)
that likewise constructs objects in-process. `F_068` *reads* the config — but only to
assert its gate rules are advisory, never to run it. Nothing in the repository loaded a
shipped config and executed it. A config is the one artifact a user actually touches, and
it was the one artifact no test exercised.

This is the same shape as the "declared but never invoked" failure the M8 execution ledger
exists to refuse, one directory over.

**Fixed.** The target gained a `store_path` param, read through the same `DATA_ROOT`
confinement every other config-named path uses (`core/_paths.py`) rather than opening a
second, unconfined filesystem seam. The generator emits `eval/store.json` alongside the
dataset. And the loop that was missing now exists — see §4.

### 1a. The journey ran, and still measured nothing

With retrieval fixed, all four scorers returned `passed=None` for all 25 items: the `echo`
stand-in emitted the raw inputs, which carry no `requirements` key, so every scorer
correctly reported "not applicable". A green run reporting `mean=0.000, pass_rate=n/a`
across the board is not a working journey; it is the vacuous one.

The generator now emits a **scripted stand-in** generator output per item, deliberately
imperfect and varied (recall 0.667–1.0, hallucination 0.0–0.333). It is derived from the
gold set, which is stated plainly wherever it appears: *its scores describe the stand-in
and measure no real generator*. A real evaluation points `inner_spec` at the system under
test and the field goes unread.

The journey test asserts non-vacuity directly — more than one distinct recall value across
the corpus — so a stand-in that degenerates back to flat 1.0 fails.

---

## 2. Correctness and hygiene findings, with what each would have cost

| # | Finding | Consequence if unfixed |
|---|---|---|
| 1 | Scorers restated the literal `"requirements_evidence"` instead of importing `REQUIREMENTS_EVIDENCE_KEY` | Renaming the constant would have silently reported **every** requirement as unsupported. The sibling `test_generation` package already imports its constant; this half of the seam had drifted from the pattern. |
| 2 | Punctuation-only requirements scored **maximally diverse** | Two empty token sets have an empty union, which the Jaccard term read as zero similarity. A backlog of `"???"` was the most diverse output the scorer could see. |
| 3 | The two halves of the diversity score used **different tokenizers** | `distinct-1` split on whitespace; Jaccard stripped punctuation. `"rejects it."` was two tokens to one half and one to the other, so the mean combined two measurements of different sets. |
| 4 | `AGENTS.md` documented an `EvidenceStore` API that does not exist | It named `fetch_record`/`verify_record` and `InMemoryEvidenceStore`. The protocol has one call, `fetch`, and the class is `MappingEvidenceStore`. This is the file agents read first. |
| 5 | The corpus generator's seeded RNG was **decorative** | Constructed per item, passed to a function that ignored it. Removing it left the committed corpus byte-identical — which is the proof it was doing nothing, and the reason it would have misled the next reader about where variation comes from. |
| 6 | `_with_split` rewrote its argument in place | Any caller reusing its own list would find it silently mutated. |
| 7 | `clock: Any` on a public constructor; `_links(req: dict, ...)` bare generic | Typing debt in the DI seam most likely to be used by an external caller. Now `RetrievalClock`/`dict[str, Any]`. |
| 8 | Dead `elif control == "mutated": pass` branch | A branch whose only content was a comment about what happens elsewhere. |

---

## 3. Coverage: the floor did not bind

The repo-wide floor is 96% and the run reported 96%+ throughout. The four new modules sat
at **92%**, hidden behind the headroom of ~2,600 tests. The uncovered lines were not
incidental — they were the negative paths:

- a malformed `requirements` payload,
- a dataset row whose `inputs` is not a mapping (untrusted input, CHARTER §4),
- a boolean read as a temperature (`isinstance(True, int)` is `True` in Python),
- a requirement with no `covers` link at all — the primary traceability failure,
- both branches of the contradiction check,
- a non-mapping evidence source,
- the live-clock and inner-declaration paths of `is_deterministic`.

All four modules are now at **100% line and branch**, and the corpus generator at 100%.

**Open debt.** `scorers/rca/__init__.py` (69%) and `scorers/rca/ranking.py` (81%) are the
lowest-covered modules in the harness. They came from `main` (PR #190), not this branch,
and are the same shape of gap: a new subpackage merged behind repo-wide headroom.

**Recommendation.** A repo-wide floor cannot answer "is *this change* tested". The two
options, in order of preference:

1. **Diff coverage in CI** (`diff-cover` against the merge base, floor ~95%). Binds on the
   lines a pull request actually adds, which is the question reviewers are asking, and adds
   no per-file bookkeeping to maintain.
2. **Per-path floors** extending `coverage-floors.yaml`'s existing `pinned_minimum`
   mechanism to named subpackages. More precise, but every new module needs a row, and a
   missing row is silent — the failure mode the file exists to prevent.

Either is a small, self-contained change. Neither is on this branch, because both alter a
protected gate file and belong in their own reviewed change.

---

## 4. Hooks and loops

### Added on this branch

- **Every shipped config is journeyed or explicitly excluded.**
  `tests/integration/test_pipeline_e2e.py` now runs each offline-runnable config in
  `config/` end to end and asserts it scores something.
  `test_every_shipped_config_is_either_journeyed_or_explicitly_excluded` compares the
  table against `config/*.yaml` in both directions, so a new config cannot ship unrun and
  a stale exclusion cannot linger. Verified against a negative control: restoring
  `store_contents: {}` makes it fail with the original `KeyError`.

  This immediately found a second, pre-existing instance: `config/trajectory_eval.yaml`
  needs `PYTHONPATH=.` as well as the allowlist its documentation names, because its target
  lives in `tests/_sut.py` and only pytest puts that on the path. `config/README.md` now
  says so.

- **Every corpus generator is watched.** Adding a corpus previously meant remembering three
  places: the Stop hook's `_CHECKERS` table, `make corpus-check`, and `make corpus-write`.
  `tests/test_claude_hooks.py` now discovers `scripts/gen_*_corpus.py` from the filesystem
  and asserts each appears in all three. The hook's table stays hand-maintained (each row
  also names the fix command, which cannot be derived) — what is now mechanical is its
  *completeness*.

### Recommended, not implemented

- **A `PostToolUse` registry-drift hook.** Registering a component requires touching about
  nine places: the `@REGISTRY.register` call, matrix rows, `FROZEN_ALIAS_MAP`,
  `docs/matrix-coverage.md`, two README registry tables, `features.yaml`, a validator, and
  `quality-gates.yml`'s `--cov=` list. Registry drift was hit twice during this work and
  both times surfaced at full-gate time. `scripts/extract_registries.py` already computes
  the answer; an advisory hook in the mould of `post-edit-size-budget.py` would move the
  finding to the edit that caused it. Advisory and fail-open, like every other hook here.

- **A `--check` for the public-surface baseline.** `stop-generated-artifacts.py` documents
  why `tests/test_public_surface.py` is excluded from its table: it has `--update` but no
  `--check`, and shelling out to pytest would make ending a turn cost a test run. Giving it
  a cheap `--check` would let it join the table and close the last generated artifact with
  no fast freshness gate.

---

## 5. Skills and agents from reusable actions

Two candidates, both in the deterministic-generator mould of `project-setup` /
`quality-gate` / `deploy` (ADR 0020) — they emit code and configuration rather than
reasoning about it.

### 5a. `corpus-forge` — a frozen-corpus generator scaffold

Two frozen corpora exist (`testgen/v1`, `requirements/v1`) and a third is specified
(`add-rca-eval-matrix`). Each independently reimplements the same eight things: sorted-key
JSON with a trailing newline, the `sha256(seed:item_id)` keyed holdout, per-item hashing, a
manifest census, a `generated_artifacts()` map, a `--write`/`--check` CLI, a corpus test
module, and the three-place freshness wiring above.

This is **not** the existing `skills/eval-corpus-forge`, which ingests real traces and
transcripts into eval datasets. This one emits the generator for a *synthetic, frozen,
byte-reproducible* corpus.

A generator skill is the right shape rather than a shared library, because the F-011 airgap
deliberately forbids the corpora from importing one another — the idiom is meant to be
copied, so the thing worth automating is the copying.

### 5b. `component-scaffold` — the register-a-component checklist

The nine touchpoints listed in §4. Emitting the skeleton plus every registration site, and
running the freshness regenerators, converts a checklist that is currently carried in
`AGENTS.md` prose into a deterministic, gradable artifact.

Both are **advisory-only proposals**: each would ship as an OpenSpec change with its own
ADR, because a skill that writes into protected paths needs the same review as any other
change to the eval surface.

---

## 6. Verification run for this review

| Gate | Result |
|---|---|
| `./scripts/quality-gate.sh all` | PASS — 2691 passed, 28 skipped, coverage above the 96% floor |
| `make check-all` | PASS for root, agent-core (919 tests), behavioral-regression, flow-corpus, flow-protocol |
| `python scripts/validate.py --tier fast --strict-git` | PASS — 65 validators, 0 skipped |
| `scripts/regression_gate.py --base-ref origin/main` | OK — no net-new lint or test findings |
| charter invariants / drift, coverage floors, size budget, guard reachability, skill marketplace | all OK |
| `architecture-drift-guard --check` | `architecture.mmd` up to date |
| `scripts/gen_requirements_corpus.py --check` | byte-identical |
| `scripts/check_protected_changes.py` | **fails by design** — this change touches `tests/**`, `config/**`, `src/eval_harness/scorers/**` and `corpora/**`, so it needs the `eval-change-approved` label and a CODEOWNER review |

`make check-all` initially failed in `claude-foundation` with
`ModuleNotFoundError: No module named 'foundation_tools'`. That is an environment artifact,
not a defect: `.claude/hooks/session-start.sh` installs that package and documents this
exact symptom, but a Cloud Agent VM does not run the Claude `SessionStart` hook. After
`pip install -e ./claude-foundation`, its gate passes.
