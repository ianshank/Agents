"""Unit tests for observable records and the strict JSONL evidence log."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend_validation.observables import Observable, ObservableError, ObservableLog, OpOutcome


def _observable(**overrides: object) -> Observable:
    fields: dict[str, object] = {
        "probe_id": "l1.tracing.roundtrip",
        "cell_id": "tracing.observability",
        "backend": "langfuse",
        "rep_index": 0,
        "ts_utc": "2026-07-20T00:00:00+00:00",
        "outcome": OpOutcome(operation="create_trace", status="ok", latency_ms=12.5, artifact_ids=("t-1",)),
        "extra": {"trace_visible": True},
    }
    fields.update(overrides)
    return Observable(**fields)  # type: ignore[arg-type]


def test_op_outcome_rejects_bad_status_and_latency() -> None:
    with pytest.raises(ObservableError, match="status"):
        OpOutcome(operation="x", status="great", latency_ms=1.0)
    with pytest.raises(ObservableError, match="latency_ms"):
        OpOutcome(operation="x", status="ok", latency_ms=-1.0)


def test_jsonl_round_trip(tmp_path: Path) -> None:
    log = ObservableLog(tmp_path / "run" / "observables.jsonl")
    first = _observable()
    second = _observable(rep_index=1, outcome=OpOutcome(operation="fetch_trace", status="error", latency_ms=3.0))
    log.append(first)
    log.append(second)
    loaded = log.read_all()
    assert loaded == [first, second]
    assert loaded[0].outcome.artifact_ids == ("t-1",)
    assert loaded[0].extra == {"trace_visible": True}


def test_reader_is_strict_about_malformed_lines(tmp_path: Path) -> None:
    path = tmp_path / "observables.jsonl"
    path.write_text('{"not json\n', encoding="utf-8")
    with pytest.raises(ObservableError, match="not valid JSON"):
        ObservableLog(path).read_all()
    path.write_text('["a", "list"]\n', encoding="utf-8")
    with pytest.raises(ObservableError, match="JSON object"):
        ObservableLog(path).read_all()
    path.write_text('{"probe_id": "x"}\n', encoding="utf-8")
    with pytest.raises(ObservableError, match="malformed observable record"):
        ObservableLog(path).read_all()


def test_blank_lines_are_tolerated_and_missing_file_is_empty(tmp_path: Path) -> None:
    log = ObservableLog(tmp_path / "observables.jsonl")
    assert log.read_all() == []  # never-written log reads as empty, not an error
    log.append(_observable())
    with log.path.open("a", encoding="utf-8") as handle:
        handle.write("\n")
    assert len(log.read_all()) == 1


def test_reader_rejects_bad_nested_shapes(tmp_path: Path) -> None:
    import json

    path = tmp_path / "observables.jsonl"
    base = _observable().to_dict()
    outcome = base["outcome"]
    assert isinstance(outcome, dict)
    corrupt_records: list[dict[str, object]] = [
        {**base, "outcome": "not-a-dict"},
        {**base, "outcome": {**outcome, "artifact_ids": "t-1"}},
        {**base, "rep_index": "zero"},
        {**base, "extra": ["not", "a", "dict"]},
    ]
    for corrupt in corrupt_records:
        path.write_text(json.dumps(corrupt) + "\n", encoding="utf-8")
        with pytest.raises(ObservableError, match="malformed observable record"):
            ObservableLog(path).read_all()
