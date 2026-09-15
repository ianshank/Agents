# trace-analytics — offline SQL sketches over replay envelopes

Unsigned experiment. **Not** a package, **not** a skill, and **not** in
`make check-all`. ClickHouse, DuckDB-as-a-harness-extra, production ingest, DLQ,
and late-arrival policy stay **gated** (CHARTER §3 observability-platform
non-goal; `openspec/changes/add-production-eval-flywheel` remains blocked).

This subtree demonstrates SQL-shaped questions against **fixture JSONL** using
the stdlib `sqlite3` module. It does not add DuckDB or ClickHouse to
`eval_harness` extras. Vendor ClickHouse remains compose-only under
`experiments/backend-validation/deploy/`.

## Isolation

- Zero writes outside this directory.
- `check_offline.py` does not import `eval_harness`.
- No `pyproject.toml` (a manifest here would pull Dependabot / coverage-grid
  obligations the experiment does not have).
- No human sign-off file: sketches are documentation plus a golden-file check,
  not production probes.

## Run

```bash
make -C experiments/trace-analytics check
# or:
python3 experiments/trace-analytics/check_offline.py
```

`--update` rewrites `expected.json` from the committed fixtures after a
deliberate query change.

## What this is not

- Not a warehouse.
- Not a path that reconstructs `AgentTrajectory` from Langfuse/Phoenix spans.
- Not an ingest daemon.
