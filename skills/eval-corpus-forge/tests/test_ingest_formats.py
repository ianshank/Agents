"""Unit tests for CSV and transcript ingestion."""
from __future__ import annotations

from forge import ingest


def _write(path, text):
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_csv_rows_become_records_with_json_cells(tmp_path):
    csv_text = (
        'prompt,expected_outcome,complexity\n'
        '"hi","{""a"": 1}",low\n'
        '"yo","{""b"": 2}",high\n'
    )
    records = ingest.load_records(_write(tmp_path / "r.csv", csv_text))
    assert [loc for _f, loc, _o in records] == ["1", "2"]
    first = records[0][2]
    assert first["prompt"] == "hi"
    assert first["expected_outcome"] == {"a": 1}  # JSON cell parsed
    assert first["complexity"] == "low"


def test_csv_empty_cells_are_omitted(tmp_path):
    csv_text = 'prompt,response\n"hi",\n'
    records = ingest.load_records(_write(tmp_path / "r.csv", csv_text))
    rec = records[0][2]
    assert rec["prompt"] == "hi"
    assert "response" not in rec  # blank cell -> missing field, not empty string


def test_csv_numeric_and_bool_coercion(tmp_path):
    csv_text = 'prompt,latency,flag\n"hi",540,true\n'
    rec = ingest.load_records(_write(tmp_path / "r.csv", csv_text))[0][2]
    assert rec["latency"] == 540
    assert rec["flag"] is True


def test_transcript_expands_user_turns(tmp_path):
    text = """
    {"session_id": "s1", "messages": [
      {"role": "user", "content": "Q1"},
      {"role": "assistant", "content": "A1", "tool_calls": [{"function": {"name": "search"}}]},
      {"role": "user", "content": "Q2"},
      {"role": "assistant", "content": "A2", "tool_names": ["cancel"]}
    ]}
    """
    records = ingest.load_records(_write(tmp_path / "c.json", text))
    assert len(records) == 2
    locs = [loc for _f, loc, _o in records]
    assert locs == ["0.t0", "0.t2"]  # one per user turn, stable turn-indexed locators
    r0 = records[0][2]
    assert r0["prompt"] == "Q1" and r0["response"] == "A1"
    assert r0["session_id"] == "s1" and r0["turn_id"] == "0"
    assert r0["trace"]["tool_names"] == ["search"]
    r1 = records[1][2]
    assert r1["trace"]["tool_names"] == ["cancel"]


def test_transcript_without_assistant_has_no_response(tmp_path):
    text = '{"messages": [{"role": "user", "content": "lonely"}]}'
    rec = ingest.load_records(_write(tmp_path / "c.json", text))[0][2]
    assert rec["prompt"] == "lonely"
    assert "response" not in rec and "trace" not in rec  # nothing fabricated


def test_transcript_turns_key_alias(tmp_path):
    text = '{"turns": [{"role": "user", "content": "hey"}]}'
    records = ingest.load_records(_write(tmp_path / "c.json", text))
    assert records[0][2]["prompt"] == "hey"


def test_plain_json_object_is_not_treated_as_transcript(tmp_path):
    text = '{"prompt": "regular", "expected_outcome": {"x": 1}}'
    records = ingest.load_records(_write(tmp_path / "p.json", text))
    assert len(records) == 1 and records[0][1] == "0"
    assert records[0][2]["prompt"] == "regular"


def test_mixed_folder_csv_json_jsonl(tmp_path):
    _write(tmp_path / "a.csv", 'prompt\n"from_csv"\n')
    _write(tmp_path / "b.jsonl", '{"prompt": "from_jsonl"}\n')
    _write(tmp_path / "c.json", '{"messages": [{"role": "user", "content": "from_transcript"}]}')
    records = ingest.load_records(str(tmp_path))
    prompts = {r[2]["prompt"] for r in records}
    assert prompts == {"from_csv", "from_jsonl", "from_transcript"}
