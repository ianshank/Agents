# Tasks: add-requirements-gen-eval-matrix

`[P]` = protected path (`eval-change-approved` label + CODEOWNERS review).
Coverage floor: root `eval_harness` **96%** (`coverage-floors.yaml`).
**Unblocked** — `add-gate-decision-provenance` (F-062) and `prove-m8-execution` (F-063) are archived.

## 1. Provenance capture

- [x] 1.1 Add `retrieved_evidence[]` to the run record via the retrieval target wrapper, not a
      scorer. Fields: `source_type`, `source_id`, `reference`, `content_sha256`, `pinnable`,
      `retrieved_at`.
- [-] 1.2 Google-native documents: fetch through `Revision.exportLinks` off `revisions.get`, which
      is revision-scoped. Do **not** use `files.export` — it has no `revisionId` parameter, so a
      hash of its output is causally unlinked from any revision id stored beside it.
- [-] 1.3 Assert non-determinism is handled, not assumed away: export the same revision twice and
      confirm the recorded hash is stable. If it is not for a given MIME type, mark that type
      unpinnable rather than storing a hash that will churn.
- [-] 1.4 Context7: record library id, the pinned version path segment when one was used, the
      query, and the `resolve-library-id` output verbatim. Mark `pinnable: false` and store no
      content hash — `query-docs` takes `{libraryId, query}` only, and the response is an
      unstructured blob from a re-crawled index.
- [x] 1.5 A `pinnable: false` record MUST carry no `content_sha256`. Test it — the whole point is
      that a reader cannot mistake a churn-prone hash for a verified one.
- [x] 1.6 Provenance verification pass: re-fetch every recorded reference and compare hashes. A
      mismatch is reported as a provenance failure, distinct from a scoring failure.

## 2. Corpus

- [x] 2.1 Synthesise 25 epics with authored gold acceptance-criteria sets and a declared source mix
      per item.
- [x] 2.2 Include contradictory-source and stale-source negative controls; confirm neither is
      distinguishable from an ordinary item by any field the target sees.
- [x] 2.3 Include items whose evidence is deliberately mutated after capture, to prove the
      provenance check actually detects drift rather than only recording it.
- [x] 2.4 Freeze at `corpora/requirements/v1/` with a manifest carrying `schema_version`, generator
      seed and per-item hashes.
- [x] 2.5 Hold out a sequestered split not used while iterating scorers.

## 3. Scorers

- [x] 3.1 **[P]** `req_ac_recall` — covered ÷ declared gold criteria, in [0,1], never inferred from
      the generated output.
- [x] 3.2 **[P]** `req_scope_hallucination` — assertions unsupported by any recorded evidence item,
      checked against the evidence record rather than the generator's account of it. Contradictory
      sources are reported, not silently resolved.
- [x] 3.3 **[P]** `req_semantic_diversity` — distinct-n plus pairwise token-set Jaccard, **pure
      Python, no numpy**. `pyproject.toml` deliberately keeps numpy off the offline path; an
      embedding variant belongs behind an optional extra that degrades to a no-op, and is not in
      this change.
- [x] 3.4 **[P]** Record generation temperature alongside every diversity score; a score without one
      is reported as uninterpretable rather than compared to the floor. The source study says
      raising temperature raises diversity, so an unqualified floor is satisfiable by a config knob.
- [x] 3.5 **[P]** `req_traceability_closure` — every link present, counted directly. An asserted
      link in generated prose does not satisfy a declared one.
- [x] 3.6 **[P]** All four report "not applicable" on absent inputs, per the `state.py` precedent.
- [x] 3.7 **[P]** Split across `scorers/requirements/{__init__,grounding,diversity}.py`; each file
      under `MAX_FILE_LINES = 500`.

## 4. Matrix, surface and registry

- [x] 4.1 **[P]** Matrix rows for all four scorers across M1, M2, M3, M5, M6 — **20 cells**.
      **Cells are not methods:** a class's dim set applies to every name in its `MATRIX_COMPONENTS`
      (`_matrix_coverage.py:645`), so one parametrized method covers a column; follow
      `TestTrajectoryScorersShared` (`tests/test_matrix_eval_tools.py:789`). Matrix classes must not
      inherit (`:609-618`).
- [x] 4.2 **[P]** Regenerate `docs/matrix-coverage.md`; freshness is gated.
- [x] 4.3 **[P]** Regenerate `tests/public_surface_baseline.json` and
      `tests/plugin_registry_baseline.json`.
- [x] 4.4 Update the scorer registry tables in **both** `README.md` and
      `src/eval_harness/README.md`.

## 5. Gating

- [x] 5.1 **[P]** Ship advisory rules only, in `config/`. No numeric threshold in the spec delta.
- [x] 5.2 **[P]** Route a sub-floor diversity score to escalation rather than failure — it is a
      coverage risk, not a correctness defect.

## 6. Validation and index

- [x] 6.1 **[P]** Add `scripts/validations/F_0NN.py` pinning: an unpinnable source carries no
      content hash; a mutated source is detected by the provenance check; a diversity score without
      a temperature is not compared to the floor.
- [x] 6.2 Claim the F-ID in `features.yaml` with `verification` bullets mirroring the spec
      scenarios; set `implemented_in`.
- [x] 6.3 Add this change to "Current changes" in `openspec/README.md` as a **link target**.
- [x] 6.4 Run `./scripts/quality-gate.sh all` and `make check-all`; confirm the 96% floor.
- [x] 6.5 Record the `spec-guardian` and `peer-reviewer` passes in `review.md`.

**Landing note (2026-09-06, F-068):** tasks 1.2–1.4 are marked `[-]` (deferred, not
done): they describe the LIVE fetcher behaviors (Drive `Revision.exportLinks`,
double-export stability, Context7 recording), which belong to the credential-gated
live-adapter follow-up. The offline change lands the record shape, the wrapper, the
verification pass, and the synthetic corpus that proves drift detection.
