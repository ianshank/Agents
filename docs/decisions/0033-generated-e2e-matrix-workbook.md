# 0033 - The e2e test matrix is a generated artifact, and it may ship as a workbook

**Status**: Accepted — lands with the end-to-end matrix generator
(`tests/_e2e_matrix.py`, `tests/test_e2e_matrix.py`). Enforcement is live from the same
change: the step inventory is parsed from the runner, the render is byte-reproducible, and
the committed artifact is freshness-gated wherever a run report exists.
**Date**: 2026-08-09

Related: [ADR 0032](0032-matrix-completeness-policy.md) (this amends its §5 "the artifact is
generated" to cover a second artifact and a second format), [ADR 0020](0020-deterministic-generator-skills.md)
(byte-stable generation as a design law), `docs/e2e-runbook.md` (the runner and tier model
this matrix reports on), F-050 / F-052 / F-053 (the manual-list-vs-derived-reality defect
class).

## Context and Problem Statement

Reporting on a full end-to-end run needs an artifact that a human can read across tiers,
and the requested format was Excel. That collides with recent history. ADR 0032 was written
partly to retire a *phantom* `eval_test_matrix.xlsx`: F-045 claimed matrices had been
"captured into" a workbook that `git log --all --diff-filter=A` shows was never committed on
any ref. `NEXT_STEPS.md` carries the correction, and ADR 0032 replaced the claim with a
generated, freshness-gated markdown file precisely because a hand-maintained workbook
"cannot drift from reality" only when nobody checks it.

So the question is not "markdown or Excel". It is: what property made the old workbook
untrustworthy, and can a workbook be shipped without reintroducing it?

Three properties made it untrustworthy, and none of them is inherent to the file format:

1. **It was authored, not derived.** Its contents were a human's claim about coverage.
2. **It was unverifiable.** Nothing regenerated it, so nothing could contradict it.
3. **It was un-diffable.** A binary blob in review is a blob; a reviewer approves the commit
   message, not the content.

## Decision

The end-to-end matrix is generated, and the workbook is one rendering of it.

1. **Derived, never authored.** The step inventory is parsed from `scripts/run_all_e2e.ps1`;
   results come from `artifacts/e2e-report/`; coverage floors, workspace members, live-step
   credentials and CI workflows are each read from the file that owns them. No step list,
   floor, or credential name is restated in the generator. A step present in a run report but
   absent from the parsed inventory is a hard error, not a dropped row.

2. **Vacuity is refused.** An empty census never renders, mirroring
   `tests/_matrix_coverage.coverage_problems`. A matrix built from nothing would report a
   clean sheet for a run that never happened.

3. **The diffable rendering is the reviewable one.** `docs/e2e-matrix/e2e-matrix.md` and
   `docs/e2e-matrix/csv/*.csv` are plain text, and the freshness gate compares both: the
   markdown, and every CSV mirror. The Provenance section is excluded from that comparison
   because it records the commit SHA at generation time, and committing the artifact creates
   a new commit -- gating it would leave the check permanently red on the very commit that
   carries the artifact. Review happens against those two renderings; the workbook adds
   presentation, not content.

4. **The workbook is byte-reproducible, so it cannot drift silently.** Two sources of
   nondeterminism were found and pinned: `openpyxl` stamps `dcterms:created`/`modified` with
   the wall clock, and `zipfile` stamps every archive entry with the local time at write.
   Both are set from the run's own provenance timestamp, and the writer is version-pinned
   (`e2e-matrix = ["openpyxl==3.1.5"]`) because a writer upgrade can change the bytes of an
   otherwise identical workbook. Regenerating from unchanged inputs produces an identical
   file, which is what makes committing it defensible. The workbook itself is *not*
   byte-compared by the gate -- it cannot be written at all without the optional extra, so
   gating it would fail for anyone who has not installed one -- and its reproducibility is
   asserted by the test suite instead.

5. **The freshness gate is honest about where it can run.** CI never executes the e2e runner,
   so no run report exists there and the gate skips rather than pretending to verify. It is
   meaningful exactly where a report is present: after a real run, before a commit.

## Consequences

**Positive.** The requested Excel deliverable exists without reviving the F-045 failure mode:
every cell traces to a parsed source, and the artifact is regenerable and comparable. The
generator also closed two latent runner defects on first contact - a shim breadcrumb printed
into every child process off Windows, and a judge parameter name (`model` vs `model_id`) that
had never been exercised because the step only ever skipped.

**Negative.** A binary file in git is still a binary file: `git diff` shows nothing useful, so
reviewers must read the markdown/CSV rendering. The workbook is therefore redundant to a
reviewer and additive only to a reader who wants a spreadsheet. Byte-reproducibility also
couples the artifact to a pinned openpyxl; bumping the pin rewrites the committed file.

**Neutral.** The generator lives under `tests/` following the F-053 precedent
(`tests/_matrix_coverage.py` + a `--check`/`--update` CLI), so it is coverage-measured by
name rather than falling into the whole-directory `--cov=scripts` denominator. It is not a
blocking CI gate, because the input it needs does not exist in CI.
