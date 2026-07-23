#!/usr/bin/env python3
"""Validate an evaluation dataset (JSONL, JSON array, or CSV) for correctness."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any


def parse_jsonl(
    content_str: str,
    file_path: Path,
    errors: list[str],
    warnings: list[str],
) -> list[tuple[int, dict[str, Any]]]:
    records: list[tuple[int, dict[str, Any]]] = []
    for line_num, line in enumerate(content_str.splitlines(), start=1):
        line_stripped = line.strip()
        if not line_stripped:
            continue
        try:
            data = json.loads(line_stripped)
            if isinstance(data, dict):
                records.append((line_num, data))
            else:
                errors.append(f"Line {line_num}: Expected JSON object, got {type(data).__name__}")
        except json.JSONDecodeError as e:
            errors.append(f"Line {line_num}: Invalid JSON: {e}")
    return records


def parse_json(
    content_str: str,
    file_path: Path,
    errors: list[str],
    warnings: list[str],
) -> list[tuple[int, dict[str, Any]]]:
    records: list[tuple[int, dict[str, Any]]] = []
    try:
        data = json.loads(content_str)
        if isinstance(data, list):
            for index, item in enumerate(data, start=1):
                if isinstance(item, dict):
                    records.append((index, item))
                else:
                    errors.append(f"Item {index}: Expected JSON object, got {type(item).__name__}")
        elif isinstance(data, dict):
            warnings.append("JSON file is a single object, not a list of objects.")
            records.append((1, data))
        else:
            errors.append(f"Expected JSON list or object, got {type(data).__name__}")
    except json.JSONDecodeError as e:
        errors.append(f"Invalid JSON file: {e}")
    return records


def parse_csv(
    content_str: str,
    file_path: Path,
    errors: list[str],
    warnings: list[str],
) -> list[tuple[int, dict[str, Any]]]:
    records: list[tuple[int, dict[str, Any]]] = []
    try:
        reader = csv.DictReader(content_str.splitlines())
        for line_num, row in enumerate(reader, start=2):
            record = dict(row)
            if "inputs" in record and isinstance(record["inputs"], str):
                inputs_val = record["inputs"].strip()
                if inputs_val:
                    try:
                        import ast

                        parsed = ast.literal_eval(inputs_val)
                        if isinstance(parsed, dict):
                            record["inputs"] = parsed
                    except Exception:
                        pass
                else:
                    del record["inputs"]
            records.append((line_num, record))
    except Exception as e:
        errors.append(f"Invalid CSV format: {e}")
    return records


def parse_fallback(
    content_str: str,
    file_path: Path,
    errors: list[str],
    warnings: list[str],
) -> list[tuple[int, dict[str, Any]]]:
    content_stripped = content_str.strip()
    if content_stripped.startswith("["):
        return parse_json(content_str, file_path, errors, warnings)
    return parse_jsonl(content_str, file_path, errors, warnings)


FORMAT_PARSERS = {
    ".jsonl": parse_jsonl,
    ".json": parse_json,
    ".csv": parse_csv,
}


def detect_and_parse(
    content_str: str,
    file_path: Path,
    errors: list[str],
    warnings: list[str],
) -> list[tuple[int, dict[str, Any]]]:
    suffix = file_path.suffix.lower()
    parser = FORMAT_PARSERS.get(suffix)
    if parser:
        return parser(content_str, file_path, errors, warnings)
    return parse_fallback(content_str, file_path, errors, warnings)


def _validate_record(
    loc: int | str,
    record: dict[str, Any],
    id_key: str,
    required_fields: list[str],
    optional_fields: list[str],
    seen_ids: set[str],
    errors: list[str],
    warnings: list[str],
) -> None:
    rec_id = record.get(id_key)

    # Validate required fields
    for field in required_fields:
        val = record.get(field)
        if val is None:
            errors.append(f"Record at location {loc}: Missing required '{field}' field")
        elif field == id_key:
            str_id = str(val).strip()
            if not str_id:
                errors.append(f"Record at location {loc}: '{field}' field is empty")
            elif str_id in seen_ids:
                errors.append(f"Record at location {loc}: Duplicate ID found: {str_id!r}")
            else:
                seen_ids.add(str_id)
        elif isinstance(val, str) and not val.strip():
            errors.append(f"Record at location {loc}: '{field}' field is empty")

    # Validate optional fields
    for field in optional_fields:
        if field in required_fields:
            continue
        val = record.get(field)
        if val is None:
            warnings.append(f"Record at location {loc} ({id_key}={rec_id}): Missing optional '{field}' field")
        elif field == "inputs":
            if not isinstance(val, dict):
                errors.append(
                    f"Record at location {loc} ({id_key}={rec_id}): 'inputs' must be a dictionary, got {type(val).__name__}"
                )
            elif not val:
                warnings.append(f"Record at location {loc} ({id_key}={rec_id}): 'inputs' dictionary is empty")
        elif isinstance(val, str) and not val.strip():
            warnings.append(f"Record at location {loc} ({id_key}={rec_id}): '{field}' field is empty")


def lint_file(
    file_path: Path,
    strict: bool,
    id_key: str = "id",
    required_fields: list[str] | None = None,
    optional_fields: list[str] | None = None,
) -> tuple[bool, int, list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    seen_ids: set[str] = set()

    # 1. Precondition: check if file exists and is a file
    if not file_path.exists():
        return False, 0, [f"File not found: {file_path}"], []
    if not file_path.is_file():
        return False, 0, [f"Path is not a file: {file_path}"], []

    # 2. Check for encoding/readability
    try:
        content_bytes = file_path.read_bytes()
    except OSError as e:
        return False, 0, [f"Cannot read file: {e}"], []

    try:
        content_str = content_bytes.decode("utf-8")
    except UnicodeDecodeError as e:
        errors.append(f"File is not valid UTF-8: {e}")
        content_str = content_bytes.decode("utf-8", errors="replace")

    # 3. Parse content
    records = detect_and_parse(content_str, file_path, errors, warnings)
    total_records = len(records)
    if total_records == 0 and not errors:
        warnings.append("Dataset is empty (contains zero valid records).")

    # 4. Lint records
    required_fields = required_fields or [id_key]
    optional_fields = optional_fields or ["inputs"]

    for loc, record in records:
        _validate_record(loc, record, id_key, required_fields, optional_fields, seen_ids, errors, warnings)

    # 5. Handle strict mode
    if strict and warnings:
        for w in warnings:
            errors.append(f"[STRICT] Warning promoted to error: {w}")
        warnings = []

    # Sort to be completely deterministic
    errors.sort()
    warnings.sort()

    passed = len(errors) == 0
    return passed, total_records, errors, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lint an evaluation dataset.")
    parser.add_argument("--in", dest="in_file", required=True, help="Path to input dataset file")
    parser.add_argument("--out", dest="out_file", help="Path to write JSON/text report")
    parser.add_argument("--format", choices=["json", "text"], default="json", help="Report format")
    parser.add_argument("--strict", action="store_true", help="Treat warnings as errors")
    parser.add_argument("--id-key", default="id", help="The name of the unique identifier key")
    parser.add_argument("--required-fields", help="Comma-separated list of required fields")
    parser.add_argument("--optional-fields", help="Comma-separated list of optional fields")
    args = parser.parse_args(argv)

    in_path = Path(args.in_file)
    if not in_path.exists() or in_path.is_dir():
        sys.stderr.write(f"Precondition failed: Input file '{in_path}' does not exist or is a directory.\n")
        return 2

    req_fields = [f.strip() for f in args.required_fields.split(",") if f.strip()] if args.required_fields else None
    opt_fields = [f.strip() for f in args.optional_fields.split(",") if f.strip()] if args.optional_fields else None

    passed, total, errors, warnings = lint_file(
        in_path,
        args.strict,
        id_key=args.id_key,
        required_fields=req_fields,
        optional_fields=opt_fields,
    )

    report_data = {
        "file": in_path.resolve().as_posix(),
        "total_records": total,
        "passed": passed,
        "errors": errors,
        "warnings": warnings,
    }

    if args.format == "json":
        report_str = json.dumps(report_data, indent=2, sort_keys=True) + "\n"
    else:
        status = "PASSED" if passed else "FAILED"
        lines = [
            f"Dataset Lint Report: {status}",
            f"File: {report_data['file']}",
            f"Total Records: {total}",
            f"Passed: {passed}",
            f"Errors ({len(errors)}):",
        ]
        for e in errors:
            lines.append(f"  - {e}")
        lines.append(f"Warnings ({len(warnings)}):")
        for w in warnings:
            lines.append(f"  - {w}")
        report_str = "\n".join(lines) + "\n"

    if args.out_file:
        out_path = Path(args.out_file)
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(report_str, encoding="utf-8")
        except OSError as e:
            sys.stderr.write(f"Failed to write report: {e}\n")
            return 2
    else:
        sys.stdout.write(report_str)

    return 0 if passed else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
