"""Step 1: discover source records and decide full-dataset vs bootstrap mode.

v1 scope: JSON, JSONL, and folders of JSON/JSONL files. CSV / transcript / trace-export /
mixed-merge parsing are deliberately deferred (see SKILL.md) — we never claim a format we do
not test.
"""
from __future__ import annotations

import json
import os
from typing import Any

# Record = (source_file, locator, raw_obj). Locator is a stable within-file position
# (line number for JSONL, array index for a JSON list, the literal "0" for a single object).
Record = tuple[str, str, dict[str, Any]]

SUPPORTED_EXTS = {".json", ".jsonl", ".ndjson"}

# Keys that, when present and non-empty, count as an observable execution artifact (§1.2).
_EXECUTION_KEYS = (
    "trace",
    "tool_calls",
    "tool_names",
    "retrieved_ids",
    "retrieved_entities",
    "response",
    "model_output",
    "workflow_completion",
    "completion_status",
)


class IngestError(Exception):
    """Raised when the source input cannot yield any prompts or scenarios."""


def _load_file(path: str) -> list[Record]:
    """Parse one .json or .jsonl file into records, preserving a stable locator."""
    ext = os.path.splitext(path)[1].lower()
    records: list[Record] = []
    try:
        with open(path, encoding="utf-8") as f:
            if ext == ".json":
                data = json.load(f)
                if isinstance(data, list):
                    for idx, obj in enumerate(data):
                        if isinstance(obj, dict):
                            records.append((path, str(idx), obj))
                elif isinstance(data, dict):
                    # A single object, or a wrapper like {"records": [...]} / {"scenarios": [...]}.
                    inner = None
                    for key in ("records", "scenarios", "data", "items"):
                        if isinstance(data.get(key), list):
                            inner = data[key]
                            break
                    if inner is not None:
                        for idx, obj in enumerate(inner):
                            if isinstance(obj, dict):
                                records.append((path, str(idx), obj))
                    else:
                        records.append((path, "0", data))
            else:  # jsonl / ndjson
                for lineno, line in enumerate(f, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        records.append((path, str(lineno), obj))
    except json.JSONDecodeError as e:
        raise IngestError(f"malformed JSON/JSONL file {path}: {e}") from e
    return records


def load_records(input_path: str) -> list[Record]:
    """Discover and parse all supported records under ``input_path``.

    Raises IngestError if the path is missing or yields no usable records.
    """
    if not os.path.exists(input_path):
        raise IngestError(f"input path does not exist: {input_path}")

    files: list[str] = []
    if os.path.isdir(input_path):
        for root, _dirs, names in os.walk(input_path):
            for name in sorted(names):
                if os.path.splitext(name)[1].lower() in SUPPORTED_EXTS:
                    files.append(os.path.join(root, name))
        files.sort()
    else:
        if os.path.splitext(input_path)[1].lower() not in SUPPORTED_EXTS:
            raise IngestError(
                f"unsupported input format {os.path.splitext(input_path)[1]!r}; "
                "v1 supports .json/.jsonl files or a folder of them"
            )
        files = [input_path]

    records: list[Record] = []
    for path in files:
        records.extend(_load_file(path))
    return records


def has_prompt(obj: dict[str, Any]) -> bool:
    """True if a record carries a prompt or scenario we can normalize (§1.1)."""
    for key in ("raw_prompt", "prompt", "input", "question", "user_message", "scenario"):
        val = obj.get(key)
        if isinstance(val, str) and val.strip():
            return True
        if isinstance(val, dict) and val:
            return True
    return False


def has_execution_artifact(obj: dict[str, Any]) -> bool:
    """True if a record carries an observable execution artifact (§1.2)."""
    for key in _EXECUTION_KEYS:
        val = obj.get(key)
        if isinstance(val, (list, dict, str)) and val:
            return True
        if isinstance(val, dict) and any(val.values()):
            return True
    return False


def detect_mode(records: list[Record]) -> str:
    """Return 'full_dataset' if any record has an execution artifact, else 'bootstrap'."""
    for _path, _loc, obj in records:
        if has_execution_artifact(obj):
            return "full_dataset"
    return "bootstrap"


def require_prompts(records: list[Record]) -> None:
    """Stop with the contract-mandated message if no prompts/scenarios are discoverable."""
    if not any(has_prompt(obj) for _p, _l, obj in records):
        # NOTE: the substring "no prompts or scenarios" is asserted by an eval — do not reword.
        raise IngestError("no prompts or scenarios discoverable in the source input")
