<!-- GENERATED DIRECTORY - do not edit its contents by hand.
     Regenerate: python tests/test_e2e_matrix.py --update
     Freshness-gated by tests/test_e2e_matrix.py::test_matrix_artifact_is_fresh. -->

# End-to-end test matrix

The rendered result of a full `scripts/run_all_e2e.ps1` run: one row per declared step,
with the tier, command, credential requirements, observed status, test counts, and the
evidence log the runner wrote.

| File | What it is |
|------|------------|
| `e2e-matrix.md` | The reviewable rendering. This is what the freshness gate compares. |
| `csv/*.csv` | One file per sheet, for diffing and for import elsewhere. |
| `e2e-test-matrix.xlsx` | The same sheets as a workbook. Byte-reproducible; presentation only. |

## Regenerating

```bash
pwsh -NoProfile -File scripts/run_all_e2e.ps1 -Tiers all -HypothesisProfile ci
python tests/test_e2e_matrix.py --update      # rewrite this directory
python tests/test_e2e_matrix.py --check       # exit 1 if it is stale
```

The workbook needs the optional extra: `pip install -e ".[e2e-matrix]"`. Without it the
markdown and CSVs are still written and the command still exits 0.

## What the columns mean

Every value is derived, never restated in the generator (see
[ADR 0033](../decisions/0033-generated-e2e-matrix-workbook.md)):

- **Tier / Step / Command / Workdir** - parsed from `scripts/run_all_e2e.ps1`. A step added
  to the runner appears here with no code change; a step in a run report that the parser
  cannot see is a hard error rather than a missing row.
- **Status / Detail / Duration** - from `artifacts/e2e-report/summary.json`. `NOT-RUN` means
  the step was never reached (its tier was not selected, or a conditional branch was not
  taken); `SKIP` means the runner reached it and declined to execute it.
- **Tests / Failures / Skipped** - from the per-suite JUnit XML, which carries more than the
  runner's own prose summary.
- **Required Credentials** - variable *names* only, read from the smokes' own declarations
  and the runner's `$liveJudges` array. Values never appear here: cells are passed through
  the smokes' redaction helper before rendering.
- **Coverage floors** - read from each unit's `pyproject.toml`, its generated
  `quality-gate.sh`, and `scripts/.coveragerc`. The test suite asserts the anchors agree.

## Reading a run honestly

A green run in an environment with no `.env` proves nothing about Tier D: every live step
skips, and the report says so. `docs/e2e-runbook.md` records the tier model and the
credentials each live step needs.
