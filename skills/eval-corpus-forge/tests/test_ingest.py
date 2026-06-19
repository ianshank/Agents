"""Unit tests for forge.ingest: discovery, format handling, mode detection, preconditions."""
from __future__ import annotations

import json

import pytest
from forge import ingest


def _write(path, text):
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_load_jsonl_file(tmp_path):
    p = _write(tmp_path / "a.jsonl", '{"prompt": "hi"}\n\n{"prompt": "yo"}\n')
    records = ingest.load_records(p)
    assert [loc for _f, loc, _o in records] == ["1", "3"]  # blank line skipped, locators stable
    assert all(f == p for f, _l, _o in records)


def test_load_json_list(tmp_path):
    p = _write(tmp_path / "a.json", json.dumps([{"prompt": "a"}, {"prompt": "b"}, "skip-non-dict"]))
    records = ingest.load_records(p)
    assert [loc for _f, loc, _o in records] == ["0", "1"]


def test_load_json_single_object(tmp_path):
    p = _write(tmp_path / "a.json", json.dumps({"prompt": "solo"}))
    records = ingest.load_records(p)
    assert len(records) == 1 and records[0][1] == "0"


@pytest.mark.parametrize("wrapper", ["records", "scenarios", "data", "items"])
def test_load_json_wrapper_keys(tmp_path, wrapper):
    p = _write(tmp_path / "a.json", json.dumps({wrapper: [{"prompt": "x"}, {"prompt": "y"}]}))
    records = ingest.load_records(p)
    assert len(records) == 2


def test_load_folder_sorted(tmp_path):
    _write(tmp_path / "b.jsonl", '{"prompt": "b"}\n')
    _write(tmp_path / "a.jsonl", '{"prompt": "a"}\n')
    _write(tmp_path / "ignore.txt", "not json")
    records = ingest.load_records(str(tmp_path))
    # only .jsonl files picked up, in deterministic (sorted) order across the folder
    assert [r[2]["prompt"] for r in records] == ["a", "b"]


def test_missing_path_raises(tmp_path):
    with pytest.raises(ingest.IngestError, match="does not exist"):
        ingest.load_records(str(tmp_path / "nope"))


def test_unsupported_extension_raises(tmp_path):
    p = _write(tmp_path / "a.yaml", "prompt: hi\n")
    with pytest.raises(ingest.IngestError, match="unsupported input format"):
        ingest.load_records(p)


def test_malformed_json_raises_ingest_error(tmp_path):
    p = _write(tmp_path / "a.jsonl", '{"prompt": "ok"}\n{bad json\n')
    with pytest.raises(ingest.IngestError, match="malformed JSON"):
        ingest.load_records(p)


@pytest.mark.parametrize(
    "obj,expected",
    [
        ({"prompt": "x"}, True),
        ({"raw_prompt": "x"}, True),
        ({"scenario": {"k": "v"}}, True),
        ({"prompt": "   "}, False),
        ({"metadata": {"a": 1}}, False),
        ({}, False),
    ],
)
def test_has_prompt(obj, expected):
    assert ingest.has_prompt(obj) is expected


@pytest.mark.parametrize(
    "obj,expected",
    [
        ({"trace": {"tool_names": ["t"]}}, True),
        ({"retrieved_ids": ["d1"]}, True),
        ({"response": "hello"}, True),
        ({"completion_status": "success"}, True),
        ({"completion_status": False}, True),   # present scalar counts as evidence
        ({"prompt": "x"}, False),
        ({"trace": {}}, False),
        ({"trace": {"tool_names": []}}, False),  # dict with only empty content is not evidence
        ({"response": "   "}, False),            # whitespace-only string is not evidence
    ],
)
def test_has_execution_artifact(obj, expected):
    assert ingest.has_execution_artifact(obj) is expected


def test_detect_mode():
    full = [("f", "1", {"prompt": "x", "response": "y"})]
    boot = [("f", "1", {"prompt": "x", "expected_outcome": {"a": 1}})]
    assert ingest.detect_mode(full) == "full_dataset"
    assert ingest.detect_mode(boot) == "bootstrap"


def test_require_prompts_message():
    with pytest.raises(ingest.IngestError, match="no prompts or scenarios"):
        ingest.require_prompts([("f", "1", {"metadata": {"x": 1}})])
    # does not raise when a prompt exists
    ingest.require_prompts([("f", "1", {"prompt": "hi"})])
