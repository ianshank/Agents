# Tasks: add-rca-eval-matrix

`[P]` = protected path (`eval-change-approved` label + CODEOWNERS review).
Coverage floor: root `eval_harness` **96%** (`coverage-floors.yaml`).
**Blocked until** `add-gate-decision-provenance` and `prove-m8-execution` land.
**Real-incident corpus is out of scope** — see `proposal.md` "What is deliberately not here".

## 1. Prototype against the existing suite

- [ ] 1.1 Build `rca_ac_at_k` and `rca_component_match` against
      `flow-corpus/data/suites/sdlc.jsonl`'s `solution_space` / `correct` shape **before** the new
      corpus exists. Read it as a fixture copy, not by reaching into `flow-corpus/` at run time —
      F-011 makes `flow_protocol` the only shared surface, and the point is to reuse the *shape*,
      not to create a dependency.
- [ ] 1.2 Confirm the scorers behave on 200 rows of known difficulty and noise. Record the observed
      distribution in `review.md`; it is the first honest baseline this capability has.

## 2. Corpus

- [ ] 2.1 Generate `corpora/rca/v1/`: per item a declared timezone, a finite candidate set, a
      confirmed cause (or none), an onset instant, and synthetic telemetry.
- [ ] 2.2 Include negative controls — items with no correct candidate and items with several — and
      confirm no field visible to the target distinguishes them.
- [ ] 2.3 Reject at load: an item with no candidate set, or with timestamps and no declared
      timezone. Both are spec requirements, both tested.
- [ ] 2.4 Freeze with a manifest carrying `schema_version`, generator seed, per-item hashes, and the
      answerable/unanswerable split counts.
- [ ] 2.5 Hold out a sequestered split not used while iterating scorers; key it with the
      `flow_corpus.holdout` idioms rather than inventing a scheme.

## 3. Baseline target

- [ ] 3.1 **[P]** Implement the `max-|Z|` baseline as a deterministic `TargetRunner`: rank
      candidates by largest absolute z-score over the item's telemetry. It produces a diagnosis, so
      it is a target — not a scorer.
- [ ] 3.2 **[P]** Add a target-kind matrix row (floor M1, M2, M3, M6).
- [ ] 3.3 Assert determinism: two runs over one item produce identical rankings; no clock, no RNG,
      no network.

## 4. Scorers

- [ ] 4.1 **[P]** `rca_ac_at_k` at k of 1, 3, 5, each labelled with its k. No unlabelled
      "accuracy" anywhere in the aggregate.
- [ ] 4.2 **[P]** Report strict and partial figures side by side, both labelled. Partial runs
      ~1.5–2× strict in this task family; an unlabelled number is not comparable to anything.
- [ ] 4.3 **[P]** `rca_component_match` — top-1 against the confirmed cause; an answer outside the
      declared candidate set is recorded as such, distinguishably from a wrong in-set choice.
- [ ] 4.4 **[P]** `rca_onset_within_tolerance` — normalise both instants to one timezone before
      comparing. Test the timezone-shifted case explicitly: a wall-clock match in the wrong zone
      must score as outside tolerance. Tolerance is a config field, not a literal.
- [ ] 4.5 **[P]** `rca_abstention_correctness` — correct only when the agent declines on an
      unanswerable item; declining on an answerable item is incorrect.
- [ ] 4.6 **[P]** `rca_false_accusation_rate` — counts a named cause on an unanswerable item.
- [ ] 4.7 **[P]** On an unanswerable item, `rca_ac_at_k` reports "not applicable" (`passed=None`),
      not zero — the `state.py` precedent.
- [ ] 4.8 **[P]** Split across `scorers/rca/{__init__,ranking,abstention}.py`; each file under
      `MAX_FILE_LINES = 500`.

## 5. Matrix, surface and registry

- [ ] 5.1 **[P]** Matrix rows for all five scorers across M1, M2, M3, M5, M6 — **25 cells** — plus
      the target row from 3.2. **Cells are not methods:** a class's dim set applies to every name in
      its `MATRIX_COMPONENTS` (`_matrix_coverage.py:645`), so one parametrized method covers a
      column; follow `TestTrajectoryScorersShared` (`tests/test_matrix_eval_tools.py:789`). Matrix
      classes must not inherit (`:609-618`).
- [ ] 5.2 **[P]** Regenerate `docs/matrix-coverage.md`; freshness is gated.
- [ ] 5.3 **[P]** Regenerate `tests/public_surface_baseline.json` (F-039 exact-equality) and
      `tests/plugin_registry_baseline.json` (M7).
- [ ] 5.4 Update the scorer and target registry tables in **both** `README.md` and
      `src/eval_harness/README.md`.

## 6. Gating

- [ ] 6.1 **[P]** Ship advisory rules only, in `config/`. Bounds are soak starting points, not spec
      values; the spec delta contains no numeric threshold.
- [ ] 6.2 **[P]** Assert the baseline target is evaluated on the identical item set whenever an
      agent is, and that both results are reported together.

## 7. Validation and index

- [ ] 7.1 **[P]** Add `scripts/validations/F_0NN.py` pinning: an item with no declared timezone is
      rejected; a timezone-shifted onset scores outside tolerance; correct abstention on an
      unanswerable item scores correct; the baseline runs on the same corpus.
- [ ] 7.2 Claim the F-ID in `features.yaml` with `verification` bullets mirroring the spec
      scenarios; set `implemented_in`.
- [ ] 7.3 Add this change to "Current changes" in `openspec/README.md` as a **link target**.
- [ ] 7.4 Run `./scripts/quality-gate.sh all` and `make check-all`; confirm the 96% floor.
- [ ] 7.5 Record the `spec-guardian` and `peer-reviewer` passes in `review.md`.
