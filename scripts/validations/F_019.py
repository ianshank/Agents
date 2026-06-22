#!/usr/bin/env python3
"""Validation script for F-019 – CSV/Parquet Dataset Sources.

Checks:
    1. ``CsvDataset`` class exists and is registered as ``"csv"`` with alias ``"csv_file"``.
    2. ``ParquetDataset`` class exists and is registered as ``"parquet"`` with alias ``"parquet_file"``.
    3. ``_validate_dataset_path`` utility exists and rejects traversal paths.
    4. CsvDataset loads a trivial CSV and yields correct EvalItem objects.
    5. Existing datasets (inline, jsonl, langfuse) are still registered.

Exit codes:
    0 – all checks passed
    1 – one or more checks failed
"""
from __future__ import annotations

import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _project_root() -> Path:
    """Resolve the project root (two levels up from this script)."""
    return Path(__file__).resolve().parent.parent.parent


def _check(condition: bool, msg: str, errors: List[str]) -> bool:
    """Log and track a check result."""
    if not condition:
        errors.append(msg)
        logger.error("FAIL: %s", msg)
        return False
    logger.info("OK: %s", msg)
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    """Run all F-019 validation checks."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)-8s %(name)s: %(message)s",
    )

    errors: List[str] = []

    # 1. CsvDataset class exists and is registered
    try:
        from eval_harness.datasets import CsvDataset
        from eval_harness.plugins import DATASETS

        _check(
            "csv" in DATASETS,
            "CsvDataset registered as 'csv'",
            errors,
        )
        _check(
            "csv_file" in DATASETS,
            "CsvDataset alias 'csv_file' registered",
            errors,
        )
        _check(
            DATASETS.resolve("csv_file") == "csv",
            "csv_file alias resolves to 'csv'",
            errors,
        )
    except ImportError as exc:
        errors.append("Cannot import CsvDataset: %s" % exc)
        logger.error("Cannot import CsvDataset: %s", exc)

    # 2. ParquetDataset class exists and is registered
    try:
        from eval_harness.datasets import ParquetDataset

        _check(
            "parquet" in DATASETS,
            "ParquetDataset registered as 'parquet'",
            errors,
        )
        _check(
            "parquet_file" in DATASETS,
            "ParquetDataset alias 'parquet_file' registered",
            errors,
        )
        _check(
            DATASETS.resolve("parquet_file") == "parquet",
            "parquet_file alias resolves to 'parquet'",
            errors,
        )
    except ImportError as exc:
        errors.append("Cannot import ParquetDataset: %s" % exc)
        logger.error("Cannot import ParquetDataset: %s", exc)

    # 3. _validate_dataset_path rejects traversal
    try:
        from eval_harness.datasets import _validate_dataset_path

        # Remove DATA_ROOT if set so the traversal check fires
        old_data_root = os.environ.pop("DATA_ROOT", None)
        try:
            traversal_rejected = False
            try:
                _validate_dataset_path("../../../etc/passwd")
            except ValueError:
                traversal_rejected = True
            _check(
                traversal_rejected,
                "_validate_dataset_path rejects path traversal",
                errors,
            )
        finally:
            if old_data_root is not None:
                os.environ["DATA_ROOT"] = old_data_root
    except ImportError as exc:
        errors.append("Cannot import _validate_dataset_path: %s" % exc)
        logger.error("Cannot import _validate_dataset_path: %s", exc)

    # 4. CsvDataset loads a trivial CSV
    try:
        with tempfile.TemporaryDirectory() as td:
            csv_path = Path(td) / "test.csv"
            csv_path.write_text("id,input,expected\na,hello,world\n", encoding="utf-8")

            old_data_root = os.environ.pop("DATA_ROOT", None)
            try:
                os.environ["DATA_ROOT"] = td
                ds = CsvDataset(path=str(csv_path))
                items = list(ds.load())
            finally:
                if old_data_root is not None:
                    os.environ["DATA_ROOT"] = old_data_root
                else:
                    os.environ.pop("DATA_ROOT", None)

            _check(
                len(items) == 1,
                "CsvDataset loaded 1 item from trivial CSV",
                errors,
            )
            if items:
                _check(
                    items[0].id == "a",
                    "CsvDataset item id == 'a'",
                    errors,
                )
                _check(
                    items[0].inputs == {"input": "hello"},
                    "CsvDataset item inputs correct",
                    errors,
                )
                _check(
                    items[0].expected == "world",
                    "CsvDataset item expected correct",
                    errors,
                )
    except Exception as exc:
        errors.append("CsvDataset load failed: %s" % exc)
        logger.error("CsvDataset load failed: %s", exc)

    # 5. Existing datasets still registered
    try:
        from eval_harness.plugins import DATASETS

        for name in ("inline", "jsonl", "langfuse"):
            _check(
                name in DATASETS,
                "Existing dataset '%s' still registered" % name,
                errors,
            )
    except Exception as exc:
        errors.append("Registry check failed: %s" % exc)
        logger.error("Registry check failed: %s", exc)

    # Summary
    if errors:
        logger.error("F-019 FAILED with %d error(s):", len(errors))
        for err in errors:
            logger.error("  • %s", err)
        return 1

    logger.info("F-019 passed ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
