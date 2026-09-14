#!/usr/bin/env python3
"""Golden-file check for offline SQL sketches (stdlib sqlite3 only).

Does not import eval_harness. Does not talk to ClickHouse or DuckDB.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures" / "envelopes.jsonl"
EXPECTED = HERE / "expected.json"


def load_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in FIXTURES.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped:
            payload = json.loads(stripped)
            if not isinstance(payload, dict):
                raise SystemExit(f"fixture line is not an object: {stripped[:40]}")
            rows.append(payload)
    return rows


def populate(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> None:
    conn.execute(
        "CREATE TABLE envelopes (envelope_id TEXT, item_id TEXT, recorded_at TEXT, tag_freshness TEXT, passed INTEGER)"
    )
    conn.execute(
        "CREATE TABLE steps (envelope_id TEXT, item_id TEXT, step_index INTEGER, "
        "kind TEXT, tool_name TEXT, timestamp_ms INTEGER)"
    )
    for row in rows:
        conn.execute(
            "INSERT INTO envelopes VALUES (?, ?, ?, ?, ?)",
            (
                row["envelope_id"],
                row["item_id"],
                row["recorded_at"],
                row["tag_freshness"],
                int(row["passed"]),
            ),
        )
        steps = row.get("steps")
        if not isinstance(steps, list):
            continue
        for index, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            conn.execute(
                "INSERT INTO steps VALUES (?, ?, ?, ?, ?, ?)",
                (
                    row["envelope_id"],
                    row["item_id"],
                    index,
                    step.get("kind"),
                    step.get("tool_name"),
                    step.get("timestamp_ms"),
                ),
            )


def query_results(conn: sqlite3.Connection) -> dict[str, Any]:
    first_fail = conn.execute(
        "SELECT e.envelope_id, e.item_id, MIN(s.step_index) AS first_error_index "
        "FROM steps s JOIN envelopes e ON e.envelope_id = s.envelope_id "
        "WHERE s.kind = 'tool_error' AND e.passed = 0 "
        "GROUP BY e.envelope_id, e.item_id "
        "ORDER BY e.envelope_id"
    ).fetchall()
    by_tag = conn.execute(
        "SELECT tag_freshness, AVG(passed) AS pass_rate, COUNT(*) AS n "
        "FROM envelopes GROUP BY tag_freshness ORDER BY tag_freshness"
    ).fetchall()
    hidden = conn.execute(
        "SELECT AVG(passed) AS global_pass, "
        "AVG(CASE WHEN tag_freshness = 'sensitive' THEN passed END) AS freshness_pass "
        "FROM envelopes"
    ).fetchone()
    sessions = conn.execute(
        "SELECT item_id, MIN(recorded_at) AS session_start, "
        "MAX(recorded_at) AS session_end, COUNT(*) AS n "
        "FROM envelopes GROUP BY item_id ORDER BY item_id"
    ).fetchall()
    latest = conn.execute(
        "SELECT e.item_id, e.envelope_id, e.recorded_at AS latest "
        "FROM envelopes e "
        "JOIN (SELECT item_id, MAX(recorded_at) AS latest FROM envelopes GROUP BY item_id) t "
        "ON e.item_id = t.item_id AND e.recorded_at = t.latest "
        "ORDER BY e.item_id"
    ).fetchall()
    return {
        "first_failing_step": [dict(row) for row in first_fail],
        "pass_rate_by_tag": [dict(row) for row in by_tag],
        "global_vs_freshness": dict(hidden) if hidden is not None else {},
        "sessions": [dict(row) for row in sessions],
        "latest_per_item": [dict(row) for row in latest],
    }


def run() -> dict[str, Any]:
    rows = load_rows()
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    populate(conn, rows)
    return query_results(conn)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true", help="rewrite expected.json")
    args = parser.parse_args(argv)
    actual = run()
    rendered = json.dumps(actual, indent=2, sort_keys=True) + "\n"
    if args.update:
        EXPECTED.write_text(rendered, encoding="utf-8")
        print(f"wrote {EXPECTED}")
        return 0
    if not EXPECTED.is_file():
        print(f"missing {EXPECTED}; run with --update", file=sys.stderr)
        return 1
    expected = EXPECTED.read_text(encoding="utf-8")
    if expected != rendered:
        print("trace-analytics sketches drifted; run --update if intentional", file=sys.stderr)
        return 1
    print("trace-analytics sketches match expected.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
