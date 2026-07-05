"""Step 1: discover source records and decide full-dataset vs bootstrap mode.

Supported inputs: JSON, JSONL/NDJSON, CSV, conversation transcripts (a JSON/JSONL object
carrying a ``messages``/``turns`` array), and folders mixing any of these. Trace-export
formats beyond the transcript shape remain out of scope.
"""

from __future__ import annotations

import csv
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# Record = (source_file, locator, raw_obj). Locator is a stable within-file position
# (line number for JSONL, array index for a JSON list, "0" for a single object, "<row>" for
# CSV rows, "<base>.t<turn>" for an expanded transcript turn).
Record = tuple[str, str, dict[str, Any]]

SUPPORTED_EXTS = {".json", ".jsonl", ".ndjson", ".csv"}

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

_TRANSCRIPT_KEYS = ("messages", "turns", "transcript")


class IngestError(Exception):
    """Raised when the source input cannot yield any prompts or scenarios."""


def _coerce_cell(value: str) -> Any:
    """Parse a CSV cell: JSON when it looks structured/scalar, else the raw string."""
    s = value.strip()
    if not s:
        return None
    if s[0] in "{[" or s in ("true", "false", "null") or _looks_numeric(s):
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return value
    return value


def _looks_numeric(s: str) -> bool:
    try:
        float(s)
    except ValueError:
        return False
    return True


def _expand_transcript(obj: dict[str, Any], base_locator: str) -> list[tuple[str, dict[str, Any]]] | None:
    """If ``obj`` is a transcript, expand each user turn into its own scenario record.

    Returns a list of (locator, record) pairs, or None if ``obj`` is not a transcript.
    Each user turn becomes a scenario; the following assistant turn supplies the response
    and any tool-call names. Nothing is invented — fields absent from the transcript stay
    absent.
    """
    messages = None
    for key in _TRANSCRIPT_KEYS:
        val = obj.get(key)
        if isinstance(val, list) and val and all(isinstance(m, dict) for m in val):
            messages = val
            break
    if messages is None:
        return None

    session_id = obj.get("session_id")
    out: list[tuple[str, dict[str, Any]]] = []
    for i, msg in enumerate(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if not (isinstance(content, str) and content.strip()):
            continue
        rec: dict[str, Any] = {"prompt": content, "turn_id": str(i)}
        if session_id is not None:
            rec["session_id"] = session_id
        # Pair with the next assistant turn for response + tool names.
        nxt = messages[i + 1] if i + 1 < len(messages) else None
        if isinstance(nxt, dict) and nxt.get("role") == "assistant":
            if isinstance(nxt.get("content"), str) and nxt["content"].strip():
                rec["response"] = nxt["content"]
            tool_names = _tool_names_from_assistant(nxt)
            if tool_names:
                rec["trace"] = {"tool_names": tool_names, "tool_invocation_order": tool_names}
        out.append((f"{base_locator}.t{i}", rec))
    return out


def _tool_names_from_assistant(msg: dict[str, Any]) -> list[str]:
    """Extract tool names from an assistant turn (OpenAI ``tool_calls`` or a ``tool_names`` list)."""
    names: list[str] = []
    calls = msg.get("tool_calls")
    if isinstance(calls, list):
        for c in calls:
            if isinstance(c, dict):
                function = c.get("function")
                fn: dict[str, Any] = function if isinstance(function, dict) else c
                name = fn.get("name")
                if isinstance(name, str):
                    names.append(name)
    explicit = msg.get("tool_names")
    if isinstance(explicit, list):
        names.extend(str(n) for n in explicit)
    return names


def _records_from_object(path: str, base_locator: str, obj: dict[str, Any]) -> list[Record]:
    """Yield records for one parsed object, expanding transcripts into per-turn scenarios."""
    expanded = _expand_transcript(obj, base_locator)
    if expanded is not None:
        return [(path, loc, rec) for loc, rec in expanded]
    return [(path, base_locator, obj)]


def _load_csv(path: str) -> list[Record]:
    """Parse a CSV file: one record per row, with JSON-aware cell coercion."""
    records: list[Record] = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for rownum, row in enumerate(reader, start=1):
            rec = {k: _coerce_cell(v) for k, v in row.items() if k is not None and v is not None and v.strip()}
            if rec:
                records.append((path, str(rownum), rec))
    return records


def _append_objects(path: str, objects: list[Any], records: list[Record]) -> int:
    """Append records parsed from indexed candidate objects; return non-object skips."""
    skipped = 0
    for idx, obj in enumerate(objects):
        if isinstance(obj, dict):
            records.extend(_records_from_object(path, str(idx), obj))
        else:
            skipped += 1
    return skipped


def _find_inner_list(data: dict[str, Any]) -> list[Any] | None:
    """The first list-valued wrapper key (records/scenarios/data/items), if any."""
    for key in ("records", "scenarios", "data", "items"):
        value = data.get(key)
        if isinstance(value, list):
            return value
    return None


def _load_json_records(path: str, f: Any) -> tuple[list[Record], int]:
    """Parse a ``.json`` payload into (records, skipped)."""
    records: list[Record] = []
    data = json.load(f)
    if isinstance(data, list):
        return records, _append_objects(path, data, records)
    if isinstance(data, dict):
        # A single object, transcript, or wrapper like {"records": [...]}.
        inner = _find_inner_list(data)
        if inner is not None:
            return records, _append_objects(path, inner, records)
        records.extend(_records_from_object(path, "0", data))
    return records, 0


def _load_jsonl_records(path: str, f: Any) -> tuple[list[Record], int]:
    """Parse a ``.jsonl`` / ``.ndjson`` stream into (records, skipped)."""
    records: list[Record] = []
    skipped = 0
    for lineno, line in enumerate(f, start=1):
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if isinstance(obj, dict):
            records.extend(_records_from_object(path, str(lineno), obj))
        else:
            skipped += 1
    return records, skipped


def _load_file(path: str) -> list[Record]:
    """Parse one supported file into records, preserving a stable locator."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        return _load_csv(path)
    try:
        with open(path, encoding="utf-8") as f:
            if ext == ".json":
                records, skipped = _load_json_records(path, f)
            else:  # jsonl / ndjson
                records, skipped = _load_jsonl_records(path, f)
    except json.JSONDecodeError as e:
        raise IngestError(f"malformed JSON/JSONL file {path}: {e}") from e
    if skipped:
        logger.warning("%s: skipped %d non-object record(s)", path, skipped)
    logger.debug("%s: loaded %d record(s)", path, len(records))
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
                "supported: .json/.jsonl/.csv files (incl. transcripts) or a folder of them"
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
    """True if a record carries an observable execution artifact (§1.2).

    A string counts only if non-whitespace; a dict counts only if it has truthy content (so
    ``{"trace": {"tool_names": []}}`` is not evidence); a list counts if non-empty; any other
    present scalar (e.g. a boolean ``completion_status``) counts.
    """
    for key in _EXECUTION_KEYS:
        val = obj.get(key)
        if val is None:
            continue
        if isinstance(val, str):
            if val.strip():
                return True
        elif isinstance(val, dict):
            if any(val.values()):
                return True
        elif isinstance(val, list):
            if val:
                return True
        else:  # present scalar (bool/int/float)
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
