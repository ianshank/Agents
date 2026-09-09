# Design: repair-e2e-matrix-provenance

## Provenance is reachable, not equal-to-HEAD

ADR 0033 §3 still excludes the Provenance *section* from the freshness byte comparison.
The new gate is a separate function (`provenance_integrity_problems`) that:

1. Parses the Commit cell.
2. Accepts an explicit waiver row (ERRATA stamps).
3. If `git cat-file -e SHA^{commit}` fails and `skip_missing_objects` is true, logs and
   returns no problems (shallow clones).
4. Otherwise requires `git merge-base --is-ancestor SHA HEAD`.

Git is injected (`GitOps` Protocol) so tests never touch the live SHA.

## Monotonicity

`parse_evidence_snapshot` reads Summary "Observed steps" and Coverage Grid "Suite Step" →
"Tests". `--update` compares the new render to the file already at `--out` and refuses a
drop unless `MONOTONICITY_WAIVERS` contains that exact pair. The 38→30 / 1627→995 drop at
`3272006` is the waived pair; a later drop of a different magnitude still fails.

`--check` also runs monotonicity after freshness. When the report matches the artifact,
counts are equal and the check is a no-op; it still catches a caller who bypasses
`--update`.

## Why not `git show SHA:docs/e2e-matrix/e2e-matrix.md` == committed body

A correct generate-then-commit stamps *generation* HEAD, then creates a new commit. The
file at that SHA is the *previous* artifact. Requiring body equality would be permanently
red — the same defect equal-to-HEAD has. Reachable ancestry is the check that survives
that workflow.
