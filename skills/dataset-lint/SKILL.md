---
name: dataset-lint
description: >
  Validate an existing evaluation dataset (JSONL/JSON/CSV) for structural
  correctness, duplicate IDs, missing required fields, and encoding issues —
  without regenerating it. Use when the user has a dataset from an external
  source, a Langfuse/BrainTrust export, or a manually-authored eval corpus
  and wants to lint, validate, check, or verify it before running evaluations.
validator_version: '2.0'
compatibility: python>=3.10
version: 1.0.0
---

# dataset-lint — portable dataset validator

Validate an existing evaluation dataset (JSONL, JSON array, or CSV) for structural correctness, duplicate record IDs, missing required fields, and encoding anomalies — without altering or regenerating the source files.

## 1. Preconditions (input contract)

- An input dataset file (`.jsonl`, `.json`, or `.csv`) exists at the specified path.
- The file is readable and uses UTF-8 encoding.
- Required fields for an evaluation item (like `id` or `inputs`) should be present on each record.
- Python 3.10+ (stdlib-only; no external dependencies are required).

## 2. Procedure (the E2E steps)

```bash
python scripts/lint_dataset.py --in <path-to-dataset> --out <path-to-report> [--strict] [--format {json,text}]
```

1. **Invoke** `scripts/lint_dataset.py` with the path to the dataset.
2. **Review** the output report. In standard mode:
   - Duplicate IDs or structural errors are flagged as **errors**.
   - Missing optional fields or empty strings are flagged as **warnings**.
   - With `--strict`, warnings are promoted to errors, failing the validation.
3. **Verify** the output report file format (JSON by default, human-readable text if selected).

## 3. Output contract (postconditions — what "done" means)

- A report is written to the specified `--out` path (or printed to stdout if omitted).
- The report includes:
  - `file`: absolute path of the linted file.
  - `total_records`: count of parsed records.
  - `passed`: `true` if no errors were found, `false` otherwise.
  - `errors`: a sorted list of errors (stable key ordering, no timestamps).
  - `warnings`: a sorted list of warnings.
- The execution is **deterministic** and **byte-stable** (re-running on the same file yields the identical report).
- The linter exits:
  - `0`: if validation passed (no errors).
  - `1`: if validation failed (errors found).
  - `2`: if a precondition failed (e.g. file missing, invalid arguments).

## 4. Failure handling

- If the input file is not found or is a directory, the command exits with exit code `2`.
- If lines are not valid JSON or CSV rows, the linter records an error for that line and continues parsing rather than crashing.

## 5. Validation gate (before declaring success)

You are **not done** until this exits 0:

```bash
python scripts/validate_skill.py --skill . --tier structural,behavioral
```

## 6. Examples

**Example 1 — linting a clean dataset**
```bash
python scripts/lint_dataset.py --in dataset.jsonl --out report.json
```
Creates `report.json` with `"passed": true`, `"total_records": 100`, `"errors": []`, and `"warnings": []`.

**Example 2 — linting a broken dataset with duplicate IDs**
```bash
python scripts/lint_dataset.py --in broken.jsonl --out report.json
```
Exits with `1`. `report.json` contains `"passed": false`, and details about duplicate `id` values in `errors`.
