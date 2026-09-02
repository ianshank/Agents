# Errata — provenance defect in the committed e2e matrix

**Filed:** 2026-09-02, during the peer review at
`docs/plans/eval-evidence-integrity/REVIEW.md` (finding P1.9). This file is hand-authored
and is not part of the generated set (`e2e-matrix.md`, `README.md`, `csv/*.csv`,
`e2e-test-matrix.xlsx`), so it is not covered by the freshness gate and does not need
regenerating alongside them.

## What is wrong

`docs/e2e-matrix/e2e-matrix.md`'s Provenance section, as committed, reads:

| Field | Value |
|---|---|
| Commit | `09337aec16e8b10588efd0e61c9d270d18ada1c4` |
| Generated at (UTC) | 2026-08-19T03:28:29+00:00 |
| Host | Windows-10-10.0.26200-SP0 |

This stamp cannot be correct. `git show 09337aec:docs/e2e-matrix/e2e-matrix.md` — the file
as it actually existed at that commit — stamps a **different** SHA (`e899249a`), a different
date (2026-08-13), and a different host (Linux). The committed artifact is not a render of
the commit it claims to be.

The history of `docs/e2e-matrix/e2e-matrix.md`'s `suite:root` test count and observed-step
count, by the commit that wrote each version:

| Doc-writing commit | Date | `suite:root` tests | Observed steps | Stamped SHA |
|---|---|---|---|---|
| `f6ff677` | 08-09 | 1627 | 38 | `3ba6461` |
| `b5d9c86` | 08-09 | 1627 | 38 | `f6ff677` |
| `e899249` | 08-13 | 1627 | 38 | `1314e12` |
| `31a7de3` | 08-13 | 1627 | 38 | `e899249` |
| `3272006` | 08-20 | **995** | **30** | `09337aec` (wrong — see above) |

Commit `3272006` ("feat(ci): add AST registry extractor, validator guard F-058, and probe
hooks") replaced a 1627-test / 38-observed render with a 995-test / 30-observed one. Tier D
went from 7 SKIP to 7 NOT-RUN, and `matrix:coverage-check` from PASS to NOT-RUN. This reads
as a run that was aborted or interrupted partway through, then committed anyway with a stamp
that does not match its own tree.

## Actual current numbers

As measured on this checkout (`9eb0520`), both suites are substantially larger than the
committed artifact claims:

| Suite | Artifact claims | Actual (this checkout) |
|---|---|---|
| `suite:root` | 995 | 1993 |
| `suite:agent-core` | 714 | 876 |

## Why the freshness gate did not catch this

`tests/test_e2e_matrix.py --check` deliberately excludes the Provenance section from its
comparison (ADR 0033 §3): gating on the commit SHA would leave the check permanently red on
the very commit that carries a fresh render, since committing the artifact always creates a
new commit after the one it was generated from. That exclusion is correct in isolation. The
gap is that nothing else checks whether a new render represents *more* evidence than the one
it replaces — a regenerated artifact with fewer observed steps and a lower test count
currently looks the same to the gate as a legitimate incremental update.

## Disposition

Tracked as Phase 8 of `docs/plans/eval-evidence-integrity/PLAN.md` ("E2E matrix integrity and
a POSIX driver"): gate the Provenance SHA as *reachable and consistent* (exists, is an
ancestor of HEAD, and re-rendering at that SHA reproduces the committed body) rather than
equal to HEAD, and add a monotonicity check so a render that drops observed-step or test
counts fails or carries an explicit waiver row. Until Phase 8 lands, treat the committed
`docs/e2e-matrix/` artifact's *results* columns (Status, Detail, Duration, Tests, Failures,
Skipped, Evidence, and the Coverage Grid's test counts) as stale; its *declared* columns
(Tier, Area, Step, Command, Workdir, Required Credentials) are independently verified current
as of this filing.
