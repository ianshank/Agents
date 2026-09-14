-- Offline SQL sketches over ReplayEnvelope JSONL.
-- DuckDB / ClickHouse are NOT harness extras. The runnable stand-ins live in
-- check_offline.py (stdlib sqlite3). QUALIFY is DuckDB/ClickHouse-only.

-- Example load (DuckDB, optional extra — not shipped)
-- CREATE VIEW envelopes AS SELECT * FROM read_json_auto('fixtures/envelopes.jsonl');

-- 1. First failing step per failed item (SQLite stand-in: MIN step_index)
-- SELECT envelope_id, item_id, MIN(step_index) FROM steps WHERE kind = 'tool_error'
-- GROUP BY envelope_id, item_id;

-- 2. Pass-rate by slice tag
-- SELECT tag_freshness, AVG(passed) AS pass_rate, COUNT(*) AS n FROM envelopes
-- GROUP BY tag_freshness;

-- 3. Tool types with largest p95 latency — omitted: fixtures do not record latency_ms.

-- 4. Global improvement hiding a freshness-slice regression
-- SELECT AVG(passed) AS global_pass,
--        AVG(CASE WHEN tag_freshness = 'sensitive' THEN passed END) AS freshness_pass
-- FROM envelopes;

-- 5. Sessionize by item_id
-- SELECT item_id, MIN(recorded_at) AS session_start, MAX(recorded_at) AS session_end,
--        COUNT(*) AS n FROM envelopes GROUP BY item_id;

-- 6. Deduplicate retries: latest recorded_at per envelope_id
-- SELECT envelope_id, MAX(recorded_at) FROM envelopes GROUP BY envelope_id;

-- 7. Judge vs human disagreement — empty until a human-label subset exists.
