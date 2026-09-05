# Design: add-requirements-gen-eval-matrix

## Provenance: what is actually recordable

The source plan's provenance ADR was the strongest idea in the whole package and its mechanism was
refuted by measurement. What follows is what the interfaces actually support.

### Google Drive

| Source-plan design | What is true | Design here |
|---|---|---|
| `files.export` + `content_sha256` as a reproducibility key | Export is **not byte-stable**: same unmodified doc, two exports six seconds apart, differing bytes at offset 10 — the ZIP DOS timestamp field carries *export* wall-clock | Fetch through `Revision.exportLinks` off `revisions.get`, which is revision-scoped |
| Store `revision_id` beside the hash | `files.export` takes only `fileId` and `mimeType` — **no `revisionId`** — so the two are causally unlinked | The reference *is* the revision-scoped link; the hash is over what that link returned |
| Trust `revision_id` alone | Google: revision lists "might be incomplete for files with a large revision history, including frequently edited Google Docs"; `keepForever` is "only applicable to files with binary content", so **native docs cannot be pinned at all** | Record unpinnable sources as unpinnable, with a retrieval timestamp, and do not present a hash as a reproducibility key |

PDF export happened to be byte-identical across two calls — Google's PDF carries no `/CreationDate`,
`/ModDate` or `/ID` — but its Info dict is `/Producer (Skia/PDF m<version> Google Docs Renderer)`.
A renderer upgrade changes those bytes with zero document edits. So even the stable format is stable
by accident, and the design does not rely on it.

Corroborating: `Revision.md5Checksum` is documented as "only applicable to files with binary content
in Drive" — Google computes no content hash for native documents. If they could offer one, they
would.

### Context7

`query-docs` accepts exactly `{libraryId, query}` and calls `GET /api/v2/context`. There is **no
version parameter**. Version is expressible only as a path segment (`/org/project/version`), only
for libraries that publish versions, and the response never echoes it back. The body is a plain
text blob — no metadata, no ETag, no snapshot identifier — produced by relevance ranking over a
continuously re-crawled index.

A hash over that blob churns for reasons unrelated to the documentation changing. So Context7 is
recorded as an **unpinnable** source: library identifier, the pinned version path segment when one
was used, the query, the `resolve-library-id` output verbatim, and a retrieval timestamp. Not a
reproducibility key dressed up as one.

(The API type carries `lastUpdateDate`, `branch`, `state` and `totalTokens` — the fields that would
make this pinnable — but the MCP layer does not render them, so they are unreachable. Worth
revisiting if that changes.)

### Evidence record shape

```json
{"source_type": "drive_doc",
 "source_id": "1AbC…",
 "reference": {"kind": "revision_export_link", "revision_id": "0B…", "mime": "text/plain"},
 "content_sha256": "…",
 "pinnable": true,
 "retrieved_at": "2026-09-05T09:14:22Z"}
```

`pinnable: false` records carry no `content_sha256`. Omitting the field is the point: a reader must
not be able to mistake a churn-prone hash for a verified one.

## `req_semantic_diversity` without numpy

The published finding motivating this scorer measured embedding similarity. This repository's
dependency tree deliberately keeps numpy and pandas off the offline path — the comments in
`pyproject.toml` say so at three separate extras — and a scorer needing a network embedding call
cannot run in the offline suite at all.

So the shipped measure is lexical and pure-Python: distinct-n over the requirement set plus pairwise
token-set Jaccard, combined into one value in [0,1]. An embedding-distance variant belongs behind an
optional extra that degrades to a no-op when absent, mirroring the `phoenix` / `braintrust` seam
pattern the repository already uses for exactly this reason. Not in this change.

**The temperature field is not decoration.** The source study states plainly that raising
temperature increases diversity. A floor gate is therefore satisfiable by a config change rather
than by better coverage — a proxy metric of exactly the kind this whole programme claims to guard
against. Recording the generation temperature alongside every score, and refusing to compare a score
that lacks one, is what keeps the metric honest. It is specified, not left to convention.

## What the judge does not score, and why that is empirical

The source plan gated on three ISO 29148 attributes and justified it with an "INCOSE-aligned
seven-trait narrowing". That construct does not exist:

- ISO/IEC/IEEE 29148:2018 enumerates **nine** characteristics: Necessary, Appropriate, Unambiguous,
  Complete, Singular, Feasible, Verifiable, Correct, Conforming.
- "Essential" and "Independent" are **not among them** — they come from one 2026 paper that
  explicitly says it *replaced* Necessary and Appropriate and *excluded* Correct and Conforming to
  reach seven. That is one author group's adaptation, not an INCOSE standard, and it narrows to
  seven, never to three.
- That paper's own numbered list has an off-by-one defect (says seven, enumerates six).
- Decisively: it measured **Claude Sonnet 3.5 at 85% agreement versus GPT-4 at 45%** on the same
  attributes. A 40-point spread means LLM-assessability is a property of the *judge*, not of the
  attribute.

So no attribute partition is encoded here. Which attributes a judge may score is a question
`extend-judge-calibration` answers per judge model against a labelled set, and this change ships no
judge-backed scorer at all. That is a smaller claim than the source made and the only one the
evidence supports.

## Corpus

`corpora/requirements/v1/` — synthesised epics with authored gold acceptance criteria, each tagged
with its source mix, plus contradictory-source and stale-source negative controls.

Synthetic first for a methodological reason, not a governance one: the provenance mechanism must be
proven against sources whose ground truth we control before it is trusted on sources we cannot
re-fetch. A provenance record that silently fails is worse than none, and the synthetic corpus is
the only place that failure is detectable — we can mutate a source and assert the hash notices.

## Gate configuration

```yaml
gate:
  rules:
    - score: req_ac_recall
      metric: mean
      min: 0.70
      report_only: true
    - score: req_scope_hallucination
      metric: mean
      max: 0.10
      report_only: true
    - score: req_semantic_diversity
      metric: mean
      min: 0.35
      report_only: true
    - score: req_traceability_closure
      metric: mean
      min: 0.60
      report_only: true
```

Advisory only; every bound is a soak starting point in config, and none appears in the spec delta.

## File layout

`src/eval_harness/scorers/requirements/{__init__,grounding,diversity}.py` — four scorers, each file
well under `MAX_FILE_LINES = 500`. Provenance capture is not a scorer: it belongs in the target
wrapper that performs retrieval, and the scorers read the recorded evidence, following the same
target-produces / scorer-reads seam as `add-testgen-eval-matrix`.

## Compiles down to

A numbered ADR at land recording the revision-scoped-export decision, the unpinnable-source
category, the offline-lexical diversity measure with its temperature obligation, and the refusal to
encode an attribute partition ahead of calibration.
