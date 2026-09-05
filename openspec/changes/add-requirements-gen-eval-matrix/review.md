# Review: add-requirements-gen-eval-matrix

**Reviewed:** the externally supplied `add-requirements-gen-eval-matrix` package, re-verified
against `28eb09d`, with its external claims re-fetched and, where possible, tested rather than read.
Full findings: `docs/plans/scenario-eval-matrices/REVIEW.md` §C3.d, §C4.

## Verdict

This package had the best idea in the source plan and the weakest evidence for it. Making provenance
a first-class requirement rather than an afterthought is right, and no other scenario package
attempted it. The mechanism proposed to deliver it does not work, and was shown not to work by
measurement rather than by argument.

The quality-scoring half rests on a construct that does not exist.

## Corrections applied

| # | Finding | Correction |
|---|---|---|
| C3.d | `files.export` + `content_sha256` as a reproducibility key | Export is **not byte-stable** (measured: same doc, two exports, differing bytes at offset 10 — ZIP timestamps carry export wall-clock). Replaced with revision-scoped `Revision.exportLinks` |
| C3.d | Store `revision_id` beside a hash of current export bytes | `files.export` has **no `revisionId` parameter**. The two were causally unlinked. The reference now *is* the revision |
| C3.d | Trust `revision_id` as the pin | Google's own docs: revision lists "might be incomplete… including frequently edited Google Docs", and `keepForever` is binary-content-only, so native docs **cannot be pinned at all**. Unpinnable sources are now recorded as unpinnable |
| C3.e | "store the resolved library ID, requested version, and a content hash" for Context7 | There is **no version parameter**; the response is an unstructured blob from a re-crawled index. Recorded as unpinnable with what is actually obtainable |
| C4.d | Gate three ISO 29148 attributes per an "INCOSE-aligned seven-trait narrowing" | That construct does not exist. Removed entirely; no judge-backed scorer ships here |
| C4.a | `req_semantic_diversity` as an embedding-distance floor | Embeddings need numpy or a network call; `pyproject.toml` keeps both off the offline path. Shipped as pure-Python distinct-n + Jaccard |
| C4.a | Diversity floor with no temperature control | The source study says raising temperature raises diversity — the floor was gameable by a config knob. Temperature is now recorded and required |
| C4.a | Diversity measured as the source measured it | The published metric is *between-run* variance against **students**. Ours is within-set. Stated in the spec so the difference is not lost |
| C4.6 | "doc-to-code traceability performs below 58% strict" | o3-mini reaches 71.1%, and "strict" there is LLM-judged *explanation* quality. The requirement now rests on measurement, not on a number |
| A7 | Matrix rows as one checkbox | 20 cells enumerated, with the parametrization mechanics stated |
| A13 | Thresholds in requirement prose | No numeric threshold in the spec delta |
| A6 | No advisory gating | Depends on `add-gate-decision-provenance` |

## Correction to round 1 of the parent review (2026-09-05, second pass)

**Round 1 §A16 claimed this change was blocked on a charter amendment alongside the RCA change.
That was wrong, and it was the weakest sentence in the round-1 review.**

- The section was wrong: "Ratified Amendments" is a subsection of CHARTER **§3**
  (`docs/CHARTER.md:86`), not §6. §6 is the escalation clause.
- The reasoning was wrong: CHARTER §3's Included list names "datasets" in scope, and every §3
  exclusion regulates a *behaviour* — training, live evals in gates, auto-merge — rather than data
  provenance. `add-production-eval-flywheel` was blocked for building an ingestion pipeline, and its
  own non-goal is *unredacted* production data, which concedes redacted committed data is not the
  bar.
- The bundling was wrong: real shipped epics are **text documents**. CHARTER §4 invariant 7
  ("Nothing host-specific is committed") bites hard on incident telemetry, where hostnames and
  service identifiers *are* the signal, and only incidentally on prose, where redaction is
  tractable. Treating the two scenarios as one governance problem was analysis by association.

This change is therefore **proposed, not blocked**. It nevertheless starts synthetic — for the
methodological reason in `proposal.md`, which is stronger than the governance one was: a provenance
mechanism must be proven against sources whose ground truth we control, and task 2.3 exists to prove
it by mutating a source and asserting the check notices.

## Findings raised by this change

**R1 — one cited source could not be found, and the search results about it were confabulated.**
The claimed CIbSE 2026 paper "LLM-Assisted INVEST Evaluation and Improvement of User Stories"
returns zero results on an exact-title search. Its article id is unindexed while its immediate
neighbours are all indexed with real titles. More seriously: repeated searches returned confident
prose asserting the paper exists, complete with author names, a DOI and an abstract — and **not one
returned URL contained the title**; one summary assigned it a DOI belonging to a different paper
entirely. A real predecessor exists (CIbSE 2025, a Spanish-language industry study of LLM user-story
quality evaluation against INVEST), which is the most likely thing the claim is a garbled version of.

Nothing in this change depends on it. It is recorded because the failure mode — a search summarizer
manufacturing a citation that a reviewer then repeats — is precisely what this capability's
provenance requirements exist to prevent, and it happened during this review.

**R2 — the two user-story diversity papers corroborate each other; the source plan read them as
opposed.** It presented one as showing lower-than-human diversity and the other as showing SOTA
models slightly exceeding humans. The second reproduces the deficit in its own Table 2, its margin
is 0.14 on a 5.0 scale with no significance test, and its "SOTA" models are GPT-3.5 Turbo and
Mistral 7B. There is no tension to resolve.

**R3 — the Austrian Post citation cannot carry "effective in production".** Six teams is right, but
the study used 25 *synthetic* stories, its practitioner survey covered **two** of them, n was 11–12
raters, there was no control group, outcomes were self-reported Likert, and the paper labels itself
an early report. It also contains counter-evidence the plan omitted: GPT-4-improved stories scored
*worse* on size, with six participants complaining they were too long. The strategic suggestion it
was used to support — pitch this as a quality gate on human-written stories before pitching it as a
generator — is still right; it just cannot lean on this as industrial precedent.

**R4 — provenance verification is a separate failure class and is specified as one.** A hash
mismatch on re-fetch is not a low score; it means the run is unauditable. Conflating the two would
let a provenance failure be averaged away into a quality metric. Task 1.6 and its scenario keep them
distinct.

## Open questions for the reviewer

1. Whether to promote the corpus to real shipped epics is a genuine question, not a blocked one. It
   needs a redaction pass and a decision about committing third-party document content. Worth asking
   on its own rather than bundled with the RCA change's much harder version of the same question.
2. The lexical diversity measure is a deliberate downgrade from the published embedding metric. If
   the soak shows it does not separate collapsed from varied backlogs, the optional-extra embedding
   variant becomes necessary rather than nice — decide that on the soak, not now.
