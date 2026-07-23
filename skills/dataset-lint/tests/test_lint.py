from __future__ import annotations

import json
import sys
from pathlib import Path

import lint_dataset


def test_lint_clean_jsonl(tmp_path):
    dataset = tmp_path / "clean.jsonl"
    dataset.write_text(
        '{"id": "item-1", "inputs": {"query": "hello"}}\n'
        "  \n"  # empty whitespace line to cover line 49
        '{"id": "item-2", "inputs": {"query": "world"}}\n',
        encoding="utf-8",
    )
    passed, total, errors, warnings = lint_dataset.lint_file(dataset, strict=False)
    assert passed
    assert total == 2
    assert not errors
    assert not warnings


def test_lint_clean_json_array(tmp_path):
    dataset = tmp_path / "clean.json"
    data = [{"id": "item-1", "inputs": {"query": "hello"}}, {"id": "item-2", "inputs": {"query": "world"}}]
    dataset.write_text(json.dumps(data), encoding="utf-8")
    passed, total, errors, warnings = lint_dataset.lint_file(dataset, strict=False)
    assert passed
    assert total == 2
    assert not errors
    assert not warnings


def test_lint_clean_csv(tmp_path):
    dataset = tmp_path / "clean.csv"
    dataset.write_text("id,inputs\nitem-1,\"{'query': 'hello'}\"\nitem-2,\"{'query': 'world'}\"\n", encoding="utf-8")
    passed, total, errors, warnings = lint_dataset.lint_file(dataset, strict=False)
    assert passed
    assert total == 2
    assert not errors
    assert not warnings


def test_lint_json_single_object(tmp_path):
    dataset = tmp_path / "single.json"
    dataset.write_text(json.dumps({"id": "item-1", "inputs": {"query": "hello"}}), encoding="utf-8")
    passed, total, errors, warnings = lint_dataset.lint_file(dataset, strict=False)
    assert passed
    assert total == 1
    assert not errors
    assert len(warnings) == 1
    assert "single object" in warnings[0]


def test_lint_duplicate_ids(tmp_path):
    dataset = tmp_path / "dup.jsonl"
    dataset.write_text(
        '{"id": "item-1", "inputs": {"query": "hello"}}\n{"id": "item-1", "inputs": {"query": "world"}}\n',
        encoding="utf-8",
    )
    passed, total, errors, _warnings = lint_dataset.lint_file(dataset, strict=False)
    assert not passed
    assert total == 2
    assert len(errors) == 1
    assert "Duplicate ID found" in errors[0]


def test_lint_missing_and_invalid_fields(tmp_path):
    dataset = tmp_path / "missing.jsonl"
    dataset.write_text(
        '{"inputs": {"query": "missing id"}}\n'
        '{"id": "", "inputs": {"query": "empty id"}}\n'
        '{"id": "item-1"}\n'
        '{"id": "item-2", "inputs": "not-a-dict"}\n'
        '{"id": "item-3", "inputs": {}}\n'
        '"not-an-object"\n',
        encoding="utf-8",
    )
    passed, total, errors, warnings = lint_dataset.lint_file(dataset, strict=False)
    assert not passed
    assert total == 5  # "not-an-object" parses but is not dict, so not added to records count
    assert len(errors) == 4  # no JSON object (line 6), missing id (line 1), empty id (line 2), inputs not dict (line 4)
    assert len(warnings) == 2  # missing inputs (line 3), empty inputs dict (line 5)


def test_lint_invalid_json(tmp_path):
    dataset = tmp_path / "invalid.jsonl"
    dataset.write_text('{"id": "item-1", "inputs": {"query": "hello"}}\n{invalid json line}\n', encoding="utf-8")
    passed, total, errors, _warnings = lint_dataset.lint_file(dataset, strict=False)
    assert not passed
    assert total == 1
    assert len(errors) == 1
    assert "Invalid JSON" in errors[0]


def test_lint_strict_mode(tmp_path):
    dataset = tmp_path / "strict.jsonl"
    dataset.write_text('{"id": "item-1"}\n', encoding="utf-8")  # missing optional inputs (warning)

    passed, _total, errors, warnings = lint_dataset.lint_file(dataset, strict=False)
    assert passed
    assert len(warnings) == 1
    assert not errors

    passed, _total, errors, warnings = lint_dataset.lint_file(dataset, strict=True)
    assert not passed
    assert len(errors) == 1
    assert "STRICT" in errors[0]
    assert not warnings


def test_lint_file_not_found(tmp_path):
    passed, _total, errors, _warnings = lint_dataset.lint_file(tmp_path / "ghost.jsonl", strict=False)
    assert not passed
    assert len(errors) == 1
    assert "File not found" in errors[0]


def test_lint_is_dir(tmp_path):
    passed, _total, errors, _warnings = lint_dataset.lint_file(tmp_path, strict=False)
    assert not passed
    assert len(errors) == 1
    assert "not a file" in errors[0]


def test_lint_invalid_utf8(tmp_path):
    dataset = tmp_path / "binary.jsonl"
    dataset.write_bytes(b'{"id": "item-1", "inputs": {"query": "\xff\xfe"}}\n')
    passed, _total, errors, _warnings = lint_dataset.lint_file(dataset, strict=False)
    assert not passed
    assert len(errors) == 1
    assert "not valid UTF-8" in errors[0]


def test_main_cli_success(tmp_path, capsys):
    dataset = tmp_path / "clean.jsonl"
    dataset.write_text('{"id": "item-1", "inputs": {"query": "hello"}}\n', encoding="utf-8")
    report = tmp_path / "report.json"

    rc = lint_dataset.main(["--in", str(dataset), "--out", str(report)])
    assert rc == 0
    assert report.exists()
    report_data = json.loads(report.read_text(encoding="utf-8"))
    assert report_data["passed"]
    assert report_data["total_records"] == 1


def test_main_cli_fail(tmp_path, capsys):
    dataset = tmp_path / "broken.jsonl"
    dataset.write_text('{"inputs": {"query": "missing id"}}\n', encoding="utf-8")

    rc = lint_dataset.main(["--in", str(dataset)])
    assert rc == 1
    out, _err = capsys.readouterr()
    assert '"passed": false' in out


def test_main_cli_precondition_fail(tmp_path, capsys):
    rc = lint_dataset.main(["--in", str(tmp_path / "ghost.jsonl")])
    assert rc == 2
    _out, err = capsys.readouterr()
    assert "does not exist" in err


def test_main_text_report(tmp_path, capsys):
    dataset = tmp_path / "broken.jsonl"
    dataset.write_text('{"inputs": {"query": "missing id"}}\n{"id": "item-1"}\n', encoding="utf-8")

    rc = lint_dataset.main(["--in", str(dataset), "--format", "text"])
    assert rc == 1
    out, _err = capsys.readouterr()
    assert "Dataset Lint Report: FAILED" in out
    assert "Errors (1):" in out
    assert "Warnings (1):" in out
    assert "missing inputs" in out or "Missing optional" in out


def test_lint_file_io_error(tmp_path, monkeypatch):
    dataset = tmp_path / "locked.jsonl"
    dataset.write_text('{"id": "item-1"}\n', encoding="utf-8")

    def mock_read_bytes(*args, **kwargs):
        raise OSError("Permission denied")

    monkeypatch.setattr(Path, "read_bytes", mock_read_bytes)
    passed, _total, errors, _warnings = lint_dataset.lint_file(dataset, strict=False)
    assert not passed
    assert len(errors) == 1
    assert "Cannot read file" in errors[0]


def test_lint_json_array_non_dict(tmp_path):
    dataset = tmp_path / "array.json"
    dataset.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    passed, _total, errors, _warnings = lint_dataset.lint_file(dataset, strict=False)
    assert not passed
    assert len(errors) == 3
    assert "Expected JSON object" in errors[0]


def test_lint_json_invalid_structure(tmp_path):
    dataset1 = tmp_path / "invalid_struct.json"
    dataset1.write_text('"just a string"', encoding="utf-8")
    passed, _total, errors, _warnings = lint_dataset.lint_file(dataset1, strict=False)
    assert not passed
    assert len(errors) == 1
    assert "Expected JSON list or object" in errors[0]

    dataset2 = tmp_path / "invalid_json.json"
    dataset2.write_text("{bad json}", encoding="utf-8")
    passed, _total, errors, _warnings = lint_dataset.lint_file(dataset2, strict=False)
    assert not passed
    assert len(errors) == 1
    assert "Invalid JSON file" in errors[0]


def test_lint_csv_abnormal_inputs(tmp_path):
    # CSV with empty inputs column
    dataset = tmp_path / "empty_inputs.csv"
    dataset.write_text("id,inputs\nitem-1,\n", encoding="utf-8")
    passed, _total, errors, warnings = lint_dataset.lint_file(dataset, strict=False)
    assert passed
    assert len(warnings) == 1
    assert "Missing optional" in warnings[0]

    # CSV with invalid inputs syntax
    dataset2 = tmp_path / "invalid_inputs.csv"
    dataset2.write_text("id,inputs\nitem-1,{invalid dict\n", encoding="utf-8")
    passed, _total, errors, _warnings = lint_dataset.lint_file(dataset2, strict=False)
    assert not passed
    assert len(errors) == 1
    assert "must be a dictionary" in errors[0]

    # CSV with non-dict inputs
    dataset3 = tmp_path / "list_inputs.csv"
    dataset3.write_text('id,inputs\nitem-1,"[1, 2]"\n', encoding="utf-8")
    passed, _total, errors, warnings = lint_dataset.lint_file(dataset3, strict=False)
    assert not passed
    assert len(errors) == 1
    assert "must be a dictionary" in errors[0]


def test_lint_csv_no_inputs(tmp_path):
    # CSV with no inputs column at all
    dataset = tmp_path / "no_inputs.csv"
    dataset.write_text("id\nitem-1\n", encoding="utf-8")
    passed, _total, _errors, warnings = lint_dataset.lint_file(dataset, strict=False)
    assert passed
    assert len(warnings) == 1
    assert "Missing optional" in warnings[0]


def test_lint_no_extension_fallback(tmp_path):
    # Fallback to JSON array detection (matching "[" prefix)
    dataset1 = tmp_path / "noext_array"
    dataset1.write_text('[{"id": "item-1"}, "invalid_item"]', encoding="utf-8")
    passed, total, errors, _warnings = lint_dataset.lint_file(dataset1, strict=False)
    assert not passed
    assert total == 1
    assert "Expected JSON object" in errors[0]

    # JSON decode error in array fallback
    dataset2 = tmp_path / "noext_array_err"
    dataset2.write_text('[{"id": "item-1"', encoding="utf-8")
    passed, _total, errors, _warnings = lint_dataset.lint_file(dataset2, strict=False)
    assert not passed
    assert "Invalid JSON" in errors[0]

    # Non-list in fallback
    dataset3 = tmp_path / "noext_non_list"
    dataset3.write_text('"just a string"', encoding="utf-8")
    passed, _total, errors, _warnings = lint_dataset.lint_file(dataset3, strict=False)
    assert not passed
    assert "Expected JSON object" in errors[0]

    # Fallback to JSONL detection (no "[" prefix, no newline)
    dataset4 = tmp_path / "noext_jsonl"
    dataset4.write_text('{"id": "item-1"}', encoding="utf-8")
    passed, total, errors, _warnings = lint_dataset.lint_file(dataset4, strict=False)
    assert passed
    assert total == 1
    assert not errors

    # Fallback to JSONL detection with error (no "[" prefix, no newline)
    dataset5 = tmp_path / "noext_jsonl_err"
    dataset5.write_text('"invalid_jsonl_item"', encoding="utf-8")
    passed, _total, errors, _warnings = lint_dataset.lint_file(dataset5, strict=False)
    assert not passed
    assert "Expected JSON object" in errors[0]

    # Fallback to JSONL detection with empty line (no "[" prefix, no newline)
    dataset6 = tmp_path / "noext_jsonl_empty"
    dataset6.write_text("   ", encoding="utf-8")
    passed, total, errors, _warnings = lint_dataset.lint_file(dataset6, strict=False)
    assert passed
    assert total == 0


def test_lint_empty_file_warning(tmp_path):
    dataset = tmp_path / "empty.jsonl"
    dataset.write_text("", encoding="utf-8")
    passed, total, _errors, warnings = lint_dataset.lint_file(dataset, strict=False)
    assert passed
    assert total == 0
    assert len(warnings) == 1
    assert "Dataset is empty" in warnings[0]


def test_main_write_report_error(tmp_path):
    dataset = tmp_path / "clean.jsonl"
    dataset.write_text('{"id": "item-1"}\n', encoding="utf-8")
    # Output path is a directory, writing will raise OSError
    rc = lint_dataset.main(["--in", str(dataset), "--out", str(tmp_path)])
    assert rc == 2


def test_main_block(tmp_path, monkeypatch):
    dataset = tmp_path / "clean.jsonl"
    dataset.write_text('{"id": "item-1"}\n', encoding="utf-8")

    import runpy

    exited = []

    script_path = Path(lint_dataset.__file__).resolve()
    monkeypatch.setattr(sys, "argv", [str(script_path), "--in", str(dataset)])

    try:
        runpy.run_path(str(script_path), run_name="__main__")
    except SystemExit as e:
        exited.append(e.code)
    
    assert exited == [0]


def test_lint_custom_id_key(tmp_path):
    dataset = tmp_path / "custom_id.jsonl"
    dataset.write_text('{"uuid": "u-1", "inputs": {"query": "hello"}}\n', encoding="utf-8")

    # Defaults to "id" so "uuid" dataset fails to validate due to missing "id"
    passed, _total, errors, _warnings = lint_dataset.lint_file(dataset, strict=False)
    assert not passed
    assert any("Missing required 'id'" in e for e in errors)

    # Custom id_key "uuid" passes!
    passed2, _total2, errors2, _warnings2 = lint_dataset.lint_file(dataset, strict=False, id_key="uuid")
    assert passed2
    assert not errors2


def test_lint_custom_required_optional_fields(tmp_path):
    dataset = tmp_path / "custom_fields.jsonl"
    dataset.write_text('{"id": "item-1", "inputs": {}, "expected": "good"}\n', encoding="utf-8")

    # With custom required fields including "expected"
    passed, _total, errors, _warnings = lint_dataset.lint_file(
        dataset,
        strict=False,
        required_fields=["id", "expected"],
        optional_fields=["inputs"],
    )
    assert passed
    assert not errors

    # With missing required custom field
    dataset_missing = tmp_path / "custom_missing.jsonl"
    dataset_missing.write_text('{"id": "item-1", "inputs": {}}\n', encoding="utf-8")
    passed2, _total2, errors2, _warnings2 = lint_dataset.lint_file(
        dataset_missing,
        strict=False,
        required_fields=["id", "expected"],
    )
    assert not passed2
    assert any("Missing required 'expected'" in e for e in errors2)


def test_main_cli_custom_fields(tmp_path):
    dataset = tmp_path / "custom_cli.jsonl"
    dataset.write_text('{"uuid": "u-1", "expected": "good"}\n', encoding="utf-8")

    rc = lint_dataset.main(
        [
            "--in",
            str(dataset),
            "--id-key",
            "uuid",
            "--required-fields",
            "uuid,expected",
            "--optional-fields",
            "inputs",
        ]
    )
    assert rc == 0


def test_lint_csv_exception(monkeypatch, tmp_path):
    import csv

    def mock_dict_reader(*args, **kwargs):
        raise Exception("csv failure")

    monkeypatch.setattr(csv, "DictReader", mock_dict_reader)
    dataset = tmp_path / "bad.csv"
    dataset.write_text("id,inputs\nitem-1,\n", encoding="utf-8")
    passed, _total, errors, _warnings = lint_dataset.lint_file(dataset, strict=False)
    assert not passed
    assert any("Invalid CSV format" in e for e in errors)


def test_lint_required_field_empty_string(tmp_path):
    dataset = tmp_path / "empty_req.jsonl"
    dataset.write_text('{"id": "item-1", "name": "  "}\n', encoding="utf-8")
    passed, _total, errors, _warnings = lint_dataset.lint_file(
        dataset,
        strict=False,
        required_fields=["id", "name"],
    )
    assert not passed
    assert any("name' field is empty" in e for e in errors)


def test_lint_overlap_fields(tmp_path):
    dataset = tmp_path / "overlap.jsonl"
    dataset.write_text('{"id": "item-1"}\n', encoding="utf-8")
    # If "id" is both required and optional, it should skip checking it as optional
    passed, _total, errors, warnings = lint_dataset.lint_file(
        dataset,
        strict=False,
        required_fields=["id"],
        optional_fields=["id"],
    )
    assert passed
    assert not errors
    assert not warnings


def test_lint_optional_field_empty_string(tmp_path):
    dataset = tmp_path / "empty_opt.jsonl"
    dataset.write_text('{"id": "item-1", "inputs": {}, "description": "   "}\n', encoding="utf-8")
    passed, _total, errors, warnings = lint_dataset.lint_file(
        dataset,
        strict=False,
        optional_fields=["inputs", "description"],
    )
    assert passed
    assert not errors
    assert any("description' field is empty" in w for w in warnings)
