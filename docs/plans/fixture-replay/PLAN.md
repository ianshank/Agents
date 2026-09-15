# Fixture replay (F-070 / ADR 0049)

Offline reload of recorded `AgentTrajectory` envelopes. Exact re-score and
counterfactual observation swap. **Not** the blocked production-eval flywheel.

## In scope

- `src/eval_harness/replay/` — envelope, JSONL archive, `replay` target, slice, report, CLI
- `eval-harness replay --mode exact|counterfactual`
- Demo beat 6 (committed fixtures)
- Answer-quality synthetic corpus with advisory gates
- `experiments/trace-analytics/` SQL sketches (unsigned)

## Out of scope

- ClickHouse / DuckDB as a harness extra
- Reconstructing trajectories from vendor spans
- `openspec/changes/add-production-eval-flywheel`
- F-036 flow_corpus ingest
- Growing `engine.py` / `comparison.py` past 500 lines

## Commands

```bash
eval-harness replay --archive demo/replay/baseline.jsonl --mode exact --offline
PYTHONPATH=. EVAL_HARNESS_CALLABLE_TARGET_ALLOWLIST=demo \
eval-harness replay --archive demo/replay/baseline.jsonl --mode counterfactual \
  --override tool.search=demo.replay_stubs:search_v2 \
  --override tool.fetch=error:stale_index \
  --override-when freshness=sensitive --offline
python scripts/gen_answer_quality_corpus.py --check
```
