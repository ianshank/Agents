# 0047 — Requirements-generation evaluation: revision-scoped provenance, unpinnable sources, offline-lexical diversity

- Status: **Accepted.**
- Date: 2026-09-06
- Related: `openspec/changes/add-requirements-gen-eval-matrix/` (design, tasks, review),
  ADR 0031 (scorer conventions), ADR 0032 (matrix obligations), ADR 0043 (the
  target-produces / scorer-reads seam this reuses), F-068.

## Context

The source plan's strongest idea was provenance for generated requirements, and its
mechanism was refuted by measurement (`design.md` §Provenance):

- Google Drive `files.export` is **not byte-stable** (the ZIP DOS timestamp carries
  export wall-clock) and takes **no `revisionId`** — a hash of its output is causally
  unlinked from any revision id stored beside it. Native docs cannot be pinned at all
  (`Revision.md5Checksum` applies to binary content only).
- Context7's `query-docs` accepts exactly `{libraryId, query}` over a continuously
  re-crawled index; the response is an unstructured blob with no version, ETag, or
  snapshot identifier. A hash over it churns for reasons unrelated to the content.

Meanwhile the diversity motivation came from an embedding-similarity study, and this
repository deliberately keeps numpy off the offline path — and a scorer needing a
network embedding call cannot run in the offline suite at all.

## Decision

1. **Revision-scoped references carry the hash; unpinnable sources carry none.**
   Evidence records are `{source_type, source_id, reference, content_sha256?,
   pinnable, retrieved_at}`. A pinnable reference (e.g. `revision_export_link` off
   `revisions.get`) carries `content_sha256` over the bytes *that reference* returned.
   An unpinnable source is recorded with `pinnable: false` and **no** `content_sha256`
   key — omitting the field is the point: a reader must not be able to mistake a
   churn-prone hash for a verified one.
2. **Provenance capture lives in the target wrapper, not a scorer.**
   `ProvenanceRecorderTarget` composes an inner target (DI or a registry
   `inner_spec`), fetches the item's declared evidence sources from an injected
   `EvidenceStore`, and publishes the records on `TargetOutput.metadata` under
   `core.types.REQUIREMENTS_EVIDENCE_KEY` — the ADR 0043 seam, so the scorers stay
   pure. `verify_provenance` re-fetches every pinnable reference and reports a
   mismatch as a **provenance failure**, a class distinct from a scoring failure.
   Live fetchers (Drive, Context7) are SDK-optional adapters behind the protocol; the
   offline path uses the in-memory store.
3. **Diversity is offline-lexical with a temperature obligation.** distinct-1 plus
   pairwise token-set Jaccard, pure Python, computed within one generated set. The
   generation temperature is recorded alongside every score; a score without one is
   reported as uninterpretable (`passed=None`), never compared to the floor — raising
   temperature raises diversity, so an unqualified floor is satisfiable by a config
   knob. An embedding variant belongs behind an optional extra that degrades to a
   no-op, and is not in this change.
4. **No attribute partition is encoded.** The source plan's "INCOSE-aligned
   seven-trait narrowing" does not exist (ISO/IEC/IEEE 29148:2018 enumerates nine
   characteristics; the seven-trait list is one paper's adaptation, with an off-by-one
   defect, and its own data shows LLM-assessability is a property of the judge, not
   the attribute). Which attributes a judge may score is an empirical question for
   `extend-judge-calibration`; this change ships no judge-backed scorer at all.
5. **Every gate rule is advisory** (`report_only`, F-062). A sub-floor diversity score
   routes to the advisory channel — the spec's escalation route — never a failure.

## Consequences

- `corpora/requirements/v1/` ships 25 synthetic epics with authored gold AC sets, a
  declared source mix, and contradictory / stale / mutated-evidence negative controls
  (the mutated controls are what prove the verification pass detects drift rather than
  only recording it).
- Four scorers × the scorer floor (M1/M2/M3/M5/M6) = 20 matrix cells, plus the
  `provenance_recorder` target row (M1/M2/M3/M6) and an M8 pipeline.
- `public_surface_baseline.json` is unchanged: the scorers subpackage declares no
  `__all__` (the state.py / trajectory.py / rca precedent).
- Real internal epics are a follow-up decision (redaction + third-party content);
  the synthetic corpus exists precisely so the provenance mechanism is proven against
  sources whose ground truth we control first.

## Alternatives considered

- **`files.export` + stored `revision_id`:** rejected — causally unlinked (no
  `revisionId` parameter) and not byte-stable.
- **Hashing Context7 blobs:** rejected — churn-prone by construction; recorded as
  unpinnable instead.
- **Embedding-based diversity:** rejected for v1 — needs numpy or a network call,
  both off the offline path.
