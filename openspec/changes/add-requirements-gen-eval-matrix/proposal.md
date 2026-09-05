# Change: add-requirements-gen-eval-matrix

**Status:** proposed · **Date:** 2026-09-05 · **Author track:** `claude/` agent lane
**Motivated by:** `docs/plans/scenario-eval-matrices/REVIEW.md` §C3.d, §C4
**Depends on:** `add-gate-decision-provenance`, `prove-m8-execution`
**Compiles down to:** `docs/plans/scenario-eval-matrices/PLAN.md` + F-IDs (claimed at land) + a design ADR.

## Why

Requirement generation from epics is the highest-ambiguity scenario of the three and the only one
whose inputs come from outside the repository. That makes **provenance**, not quality scoring, the
first problem: a generated requirement whose supporting evidence cannot be re-fetched is not
falsifiable, and every downstream quality number computed over it is unauditable.

The source plan understood this and proposed the right shape — capture every retrieved evidence
item with source type, identifier, revision and a content hash. Its mechanism does not work. Two
things were verified by measurement rather than documentation:

- **Google Drive `files.export` is not byte-stable.** The same unmodified document exported twice
  six seconds apart produces different bytes — the ZIP entry timestamps carry the *export*
  wall-clock, not the document's. PDF export happened to be stable across two calls, but its
  producer string embeds the renderer version, so a Google-side upgrade silently invalidates every
  stored hash with zero document edits.
- **`files.export` cannot target a revision.** Its parameters are `fileId` and `mimeType`; there is
  no `revisionId`. Storing a revision identifier beside a hash of *current* export bytes pairs two
  things with no causal link — the document can change between the revision read and the export.

So a `content_sha256` over `files.export` output is a change-detector that fires on no change. As a
reproducibility key it is worse than nothing, because it looks like one.

## What changes

**1. Provenance capture that actually reproduces.**
Every retrieved evidence item is recorded with its source type, identifier, the revision-scoped
export path used to fetch it, and a hash of those bytes. For Google-native documents that means
fetching through `Revision.exportLinks` off `revisions.get`, which *is* revision-scoped, rather than
`files.export`, which is not.

**2. Four deterministic scorers.**
`req_ac_recall`, `req_scope_hallucination`, `req_semantic_diversity`, `req_traceability_closure`.
None is judge-backed in this change.

**3. A corpus of epics with post-hoc gold acceptance criteria**, including contradictory-source and
stale-source negative controls.

## Scope / non-goals

- **Non-goal: judge-scored requirement quality.** The source plan proposed gating on three
  ISO 29148 attributes — unambiguity, verifiability, singularity — on the strength of a claimed
  "INCOSE-aligned seven-trait narrowing". That narrowing is one 2026 paper's private 9→7
  re-labelling, not an INCOSE construct; "Essential" and "Independent" are not 29148 terms at all
  (29148 enumerates nine: Necessary, Appropriate, Unambiguous, Complete, Singular, Feasible,
  Verifiable, Correct, Conforming); and the same paper measured **Claude Sonnet 3.5 at 85% agreement
  against GPT-4 at 45%** on those attributes. LLM-assessability is model-specific, not
  attribute-intrinsic. Which attributes a judge may score is therefore an empirical question for
  `extend-judge-calibration` to answer per judge model, not a literature claim to encode in a spec.
- **Non-goal: a content hash over `files.export`.** See above. Superseded by revision-scoped export.
- **Non-goal: a Context7 "requested version" field.** `query-docs` accepts `{libraryId, query}` and
  nothing else; version is expressible only as a path segment, only for libraries that publish
  versions, and the response never echoes it back. What is recordable is recorded; what is not, is
  not invented.
- **Non-goal: real internal epics in this change.** See below.

## On corpus provenance

Round 1 of the parent review claimed this change was blocked alongside the RCA change on a charter
amendment. **That was wrong and is retracted** (see `review.md`). Real shipped epics are text
documents; CHARTER §3 lists "datasets" in scope and its exclusions regulate behaviours rather than
data provenance; and CHARTER §4 invariant 7 — "Nothing host-specific is committed" — bites only
incidentally on prose, where redaction is tractable in a way it is not for telemetry.

This change nevertheless starts on **synthesised epics with authored gold criteria**, for a
methodological reason rather than a governance one: the provenance mechanism must be proven against
sources whose ground truth we control before it is trusted on sources we cannot re-fetch. A
provenance record that silently fails is worse than none, and a synthetic corpus is the only place
that failure is detectable.

Promoting the corpus to real epics is a follow-up that needs a redaction pass and a decision about
committing third-party document content — a smaller question than the RCA change faces, and one
worth asking separately rather than bundling.

## Impact

- **Protected paths:** `src/eval_harness/scorers/**`, `config/**`, `features.yaml`,
  `scripts/validations/**`, root `tests/**`.
- Root `eval_harness` coverage floor **96%**.
- Matrix obligation: 4 scorers × the scorer floor = **20 cells**.
- Both surface baselines regenerated; both README registry tables updated.
- No new runtime dependency. `req_semantic_diversity` ships as a pure-Python lexical measure
  specifically to avoid pulling numpy into a dependency tree that deliberately excludes it.
