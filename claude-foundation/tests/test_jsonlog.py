from __future__ import annotations

import io
import json
import logging
from pathlib import Path

import pytest

from foundation_tools import jsonlog


@pytest.fixture(autouse=True)
def _fresh_loggers() -> None:
    # get_logger reuses configured loggers by name; isolate each test.
    for name in list(logging.Logger.manager.loggerDict):
        if name.startswith("t-jsonlog"):
            logging.Logger.manager.loggerDict.pop(name)


def _read_lines(stream: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_emits_one_json_object_per_line_with_extras() -> None:
    stream = io.StringIO()
    logger = jsonlog.get_logger("t-jsonlog-a", stream=stream)
    logger.info("thing happened", extra={"count": 3, "path": "x.py"})
    logger.warning("second")
    records = _read_lines(stream)
    assert [r["event"] for r in records] == ["thing happened", "second"]
    assert records[0]["count"] == 3 and records[0]["path"] == "x.py"
    assert records[0]["level"] == "INFO" and records[1]["level"] == "WARNING"
    assert "ts" in records[0] and records[0]["logger"] == "t-jsonlog-a"


def test_exception_info_is_serialized() -> None:
    stream = io.StringIO()
    logger = jsonlog.get_logger("t-jsonlog-b", stream=stream)
    try:
        raise ValueError("boom")
    except ValueError:
        logger.exception("failed")
    (record,) = _read_lines(stream)
    assert "boom" in str(record["error"])


def test_file_output_when_log_dir_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(jsonlog.LOG_DIR_ENV, str(tmp_path / "logs"))
    logger = jsonlog.get_logger("t-jsonlog-c", stream=io.StringIO())
    logger.info("persisted")
    log_file = tmp_path / "logs" / "t-jsonlog-c.jsonl"
    assert log_file.exists()
    assert json.loads(log_file.read_text())["event"] == "persisted"


def test_level_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(jsonlog.LOG_LEVEL_ENV, "ERROR")
    stream = io.StringIO()
    logger = jsonlog.get_logger("t-jsonlog-d", stream=stream)
    logger.info("hidden")
    logger.error("shown")
    records = _read_lines(stream)
    assert [r["event"] for r in records] == ["shown"]


def test_repeat_calls_reuse_handlers() -> None:
    stream = io.StringIO()
    first = jsonlog.get_logger("t-jsonlog-e", stream=stream)
    second = jsonlog.get_logger("t-jsonlog-e", stream=io.StringIO())
    assert first is second
    assert len(first.handlers) == 1
