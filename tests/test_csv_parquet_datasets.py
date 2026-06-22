"""Tests for CSV and Parquet dataset sources (F-019).

Tests cover:
- CSV default/custom column mappings
- CSV missing columns, empty files, BOM handling
- Parquet loading and import error handling
- Path confinement via DATA_ROOT
- Backwards compatibility of existing datasets
"""

from __future__ import annotations

import logging
import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from eval_harness.core.types import EvalItem
from eval_harness.datasets import (
    CsvDataset,
    InlineDataset,
    JsonlDataset,
    ParquetDataset,
    _validate_dataset_path,
)
from eval_harness.plugins import DATASETS

# ---------------------------------------------------------------------------
# CSV fixtures (tmp_path based)
# ---------------------------------------------------------------------------


@pytest.fixture()
def csv_default(tmp_path: Path) -> Path:
    """CSV with default column names: id, input, expected."""
    p = tmp_path / "default.csv"
    p.write_text(
        textwrap.dedent("""\
            id,input,expected
            a,hello,world
            b,foo,bar
        """),
        encoding="utf-8",
    )
    return p


@pytest.fixture()
def csv_custom(tmp_path: Path) -> Path:
    """CSV with non-default column names."""
    p = tmp_path / "custom.csv"
    p.write_text(
        textwrap.dedent("""\
            row_id,question,context,answer,source
            1,What is AI?,tech,Artificial Intelligence,wiki
            2,What is ML?,tech,Machine Learning,textbook
        """),
        encoding="utf-8",
    )
    return p


@pytest.fixture()
def csv_empty(tmp_path: Path) -> Path:
    """Completely empty CSV file."""
    p = tmp_path / "empty.csv"
    p.write_text("", encoding="utf-8")
    return p


@pytest.fixture()
def csv_header_only(tmp_path: Path) -> Path:
    """CSV with header but no data rows."""
    p = tmp_path / "header_only.csv"
    p.write_text("id,input,expected\n", encoding="utf-8")
    return p


@pytest.fixture()
def csv_bom(tmp_path: Path) -> Path:
    """CSV with UTF-8 BOM."""
    p = tmp_path / "bom.csv"
    p.write_bytes(b"\xef\xbb\xbfid,input,expected\r\na,hello,world\r\n")
    return p


@pytest.fixture()
def csv_missing_col(tmp_path: Path) -> Path:
    """CSV missing the default 'input' column."""
    p = tmp_path / "missing.csv"
    p.write_text("id,question,expected\na,hello,world\n", encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# CSV Tests
# ---------------------------------------------------------------------------


class TestCsvDatasetDefaultColumns:
    """CSV with default column mappings."""

    def test_load_items(self, csv_default: Path) -> None:
        ds = CsvDataset(path=str(csv_default))
        items = list(ds.load())
        assert len(items) == 2
        assert items[0].id == "a"
        assert items[0].inputs == {"input": "hello"}
        assert items[0].expected == "world"

    def test_item_ids(self, csv_default: Path) -> None:
        items = list(CsvDataset(path=str(csv_default)).load())
        assert [i.id for i in items] == ["a", "b"]


class TestCsvDatasetCustomColumns:
    """CSV with custom column mappings."""

    def test_custom_mappings(self, csv_custom: Path) -> None:
        ds = CsvDataset(
            path=str(csv_custom),
            id_column="row_id",
            input_columns=["question", "context"],
            expected_column="answer",
            metadata_columns=["source"],
        )
        items = list(ds.load())
        assert len(items) == 2
        assert items[0].id == "1"
        assert items[0].inputs == {"question": "What is AI?", "context": "tech"}
        assert items[0].expected == "Artificial Intelligence"
        assert items[0].metadata == {"source": "wiki"}

    def test_fallback_id_when_column_missing(self, csv_custom: Path) -> None:
        """When id_column doesn't exist, fallback to row index."""
        ds = CsvDataset(
            path=str(csv_custom),
            id_column="nonexistent",
            input_columns=["question"],
            expected_column="answer",
        )
        items = list(ds.load())
        # row.get("nonexistent", i) returns i (the fallback)
        assert items[0].id == "0"
        assert items[1].id == "1"


class TestCsvDatasetMissingColumn:
    """CSV missing required input columns."""

    def test_raises_value_error(self, csv_missing_col: Path) -> None:
        ds = CsvDataset(path=str(csv_missing_col))
        with pytest.raises(ValueError, match="missing required input column"):
            ds.load()

    def test_error_message_includes_available(self, csv_missing_col: Path) -> None:
        ds = CsvDataset(path=str(csv_missing_col))
        with pytest.raises(ValueError, match="Available columns"):
            ds.load()


class TestCsvDatasetEmpty:
    """Empty CSV files."""

    def test_completely_empty(self, csv_empty: Path) -> None:
        ds = CsvDataset(path=str(csv_empty))
        items = list(ds.load())
        assert items == []

    def test_header_only(self, csv_header_only: Path) -> None:
        ds = CsvDataset(path=str(csv_header_only))
        items = list(ds.load())
        assert items == []


class TestCsvDatasetBom:
    """CSV with UTF-8 BOM."""

    def test_bom_handled(self, csv_bom: Path) -> None:
        ds = CsvDataset(path=str(csv_bom))
        items = list(ds.load())
        assert len(items) == 1
        # utf-8-sig strips the BOM, so column name should be clean
        assert items[0].id == "a"
        assert items[0].inputs == {"input": "hello"}


class TestCsvDatasetMetadataColumns:
    """Metadata column handling."""

    def test_no_metadata_by_default(self, csv_default: Path) -> None:
        ds = CsvDataset(path=str(csv_default))
        items = list(ds.load())
        assert items[0].metadata == {}

    def test_metadata_column_missing_returns_none(self, csv_default: Path) -> None:
        """If a metadata_columns entry doesn't exist, it gets None."""
        ds = CsvDataset(
            path=str(csv_default),
            metadata_columns=["nonexistent"],
        )
        items = list(ds.load())
        assert items[0].metadata == {"nonexistent": None}


# ---------------------------------------------------------------------------
# Parquet Tests
# ---------------------------------------------------------------------------


class TestParquetDataset:
    """Parquet dataset loading."""

    @pytest.fixture()
    def parquet_file(self, tmp_path: Path) -> Path:
        """Create a small parquet fixture file."""
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError:
            pytest.skip("pyarrow not installed")

        table = pa.table(
            {
                "id": ["x", "y"],
                "input": ["hello", "world"],
                "expected": ["hi", "earth"],
                "source": ["test", "test2"],
            }
        )
        p = tmp_path / "data.parquet"
        pq.write_table(table, str(p))
        return p

    def test_load_default_columns(self, parquet_file: Path) -> None:
        ds = ParquetDataset(path=str(parquet_file))
        items = list(ds.load())
        assert len(items) == 2
        assert items[0].id == "x"
        assert items[0].inputs == {"input": "hello"}
        assert items[0].expected == "hi"

    def test_custom_columns(self, parquet_file: Path) -> None:
        ds = ParquetDataset(
            path=str(parquet_file),
            input_columns=["input"],
            metadata_columns=["source"],
        )
        items = list(ds.load())
        assert items[0].metadata == {"source": "test"}

    def test_missing_input_column(self, parquet_file: Path) -> None:
        ds = ParquetDataset(
            path=str(parquet_file),
            input_columns=["nonexistent"],
        )
        with pytest.raises(ValueError, match="missing required input column"):
            ds.load()


class TestParquetImportError:
    """Parquet import error when pyarrow is not installed."""

    def test_import_error_message(self, tmp_path: Path) -> None:
        """Mock pyarrow being absent to verify the error message."""
        p = tmp_path / "fake.parquet"
        p.write_bytes(b"fake")
        ds = ParquetDataset(path=str(p))

        # Patch the import inside load()
        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "pyarrow.parquet" or name == "pyarrow":
                raise ImportError("No module named 'pyarrow'")
            return real_import(name, *args, **kwargs)

        with (
            patch.object(builtins, "__import__", side_effect=mock_import),
            pytest.raises(ImportError, match="pyarrow is required"),
        ):
            ds.load()


# ---------------------------------------------------------------------------
# Path confinement tests
# ---------------------------------------------------------------------------


class TestPathConfinement:
    """Tests for _validate_dataset_path path confinement."""

    def test_reject_traversal_without_data_root(self, monkeypatch) -> None:
        """Reject '../../../etc/passwd' without DATA_ROOT."""
        monkeypatch.delenv("DATA_ROOT", raising=False)
        with pytest.raises(ValueError, match="Path traversal"):
            _validate_dataset_path("../../../etc/passwd")

    def test_reject_traversal_in_middle(self, monkeypatch) -> None:
        """Reject 'data/../../../etc/passwd' without DATA_ROOT."""
        monkeypatch.delenv("DATA_ROOT", raising=False)
        with pytest.raises(ValueError, match="Path traversal"):
            _validate_dataset_path("data/../../../etc/passwd")

    def test_allow_with_data_root_inside(self, tmp_path: Path, monkeypatch) -> None:
        """Allow absolute path when it's inside DATA_ROOT."""
        data_dir = tmp_path / "datasets"
        data_dir.mkdir()
        f = data_dir / "test.csv"
        f.write_text("id,input\n", encoding="utf-8")

        monkeypatch.setenv("DATA_ROOT", str(data_dir))
        result = _validate_dataset_path(str(f))
        assert result == f.resolve()

    def test_reject_outside_data_root(self, tmp_path: Path, monkeypatch) -> None:
        """Reject paths that resolve outside DATA_ROOT."""
        data_dir = tmp_path / "datasets"
        data_dir.mkdir()
        outside = tmp_path / "other" / "secret.csv"

        monkeypatch.setenv("DATA_ROOT", str(data_dir))
        with pytest.raises(ValueError, match="outside DATA_ROOT"):
            _validate_dataset_path(str(outside))

    def test_absolute_path_warning_without_data_root(self, tmp_path: Path, monkeypatch, caplog) -> None:
        """Absolute path without DATA_ROOT emits a warning."""
        monkeypatch.delenv("DATA_ROOT", raising=False)
        abs_path = tmp_path / "data.csv"
        abs_path.write_text("id,input\n", encoding="utf-8")

        with caplog.at_level(logging.WARNING, logger="eval_harness.datasets"):
            result = _validate_dataset_path(str(abs_path))
        assert result == abs_path.resolve()
        assert "without DATA_ROOT" in caplog.text

    def test_relative_path_no_traversal_ok(self, monkeypatch) -> None:
        """A simple relative path without traversal should resolve OK."""
        monkeypatch.delenv("DATA_ROOT", raising=False)
        # Just verify it doesn't raise (file doesn't need to exist for validation)
        result = _validate_dataset_path("data/test.csv")
        assert result.name == "test.csv"


# ---------------------------------------------------------------------------
# Registry integration tests
# ---------------------------------------------------------------------------


class TestRegistryIntegration:
    """Verify CSV/Parquet are registered and aliases work."""

    def test_csv_in_registry(self) -> None:
        assert "csv" in DATASETS

    def test_csv_file_alias(self) -> None:
        assert "csv_file" in DATASETS
        assert DATASETS.resolve("csv_file") == "csv"

    def test_parquet_in_registry(self) -> None:
        assert "parquet" in DATASETS

    def test_parquet_file_alias(self) -> None:
        assert "parquet_file" in DATASETS
        assert DATASETS.resolve("parquet_file") == "parquet"


# ---------------------------------------------------------------------------
# Backwards compatibility
# ---------------------------------------------------------------------------


class TestBackwardsCompatibility:
    """Ensure existing dataset types still work after changes."""

    def test_inline_dataset_unchanged(self) -> None:
        ds = InlineDataset(items=[{"id": "a", "inputs": {"x": 1}, "expected": 2}])
        items = list(ds.load())
        assert items[0].id == "a" and items[0].expected == 2

    def test_jsonl_dataset_unchanged(self, tmp_path: Path) -> None:
        p = tmp_path / "d.jsonl"
        p.write_text(
            '{"id":"a","inputs":{"x":1}}\n\n{"id":"b","inputs":{"x":2}}\n',
            encoding="utf-8",
        )
        items = list(JsonlDataset(path=str(p)).load())
        assert [i.id for i in items] == ["a", "b"]

    def test_inline_in_registry(self) -> None:
        assert "inline" in DATASETS

    def test_jsonl_in_registry(self) -> None:
        assert "jsonl" in DATASETS

    def test_langfuse_in_registry(self) -> None:
        assert "langfuse" in DATASETS


class TestDatasetEdgeCases:
    """Tests for dataset edge cases, duplicate columns/IDs, encodings, and traversal."""

    def test_csv_duplicate_columns(self, tmp_path: Path) -> None:
        p = tmp_path / "dup_cols.csv"
        p.write_text("id,input,input\na,hello,world\n", encoding="utf-8")
        ds = CsvDataset(path=str(p))
        with pytest.raises(ValueError, match="duplicate column names"):
            ds.load()

    def test_csv_latin1_encoding(self, tmp_path: Path) -> None:
        p = tmp_path / "latin1.csv"
        # accent character in latin-1
        p.write_bytes(b"id,input,expected\r\na,h\xe9llo,world\r\n")
        ds = CsvDataset(path=str(p), encoding="latin-1")
        items = list(ds.load())
        assert len(items) == 1
        assert items[0].inputs == {"input": "héllo"}

    def test_csv_quoted_newlines(self, tmp_path: Path) -> None:
        p = tmp_path / "newlines.csv"
        p.write_bytes(b'id,input,expected\na,"hello\nworld",ok\n')
        ds = CsvDataset(path=str(p))
        items = list(ds.load())
        assert len(items) == 1
        assert items[0].inputs == {"input": "hello\nworld"}

    def test_jsonl_path_confinement(self, monkeypatch) -> None:
        """Reject '../../../etc/passwd' traversal in JsonlDataset."""
        monkeypatch.delenv("DATA_ROOT", raising=False)
        with pytest.raises(ValueError, match="Path traversal"):
            JsonlDataset("../../../etc/passwd")

    def test_engine_duplicate_ids_warning(self, caplog) -> None:
        """Engine should log a warning when duplicate item IDs are found in a dataset."""
        from eval_harness.config.models import EvalConfig
        from eval_harness.core.interfaces import TargetRunner
        from eval_harness.engine import EvalEngine

        config = EvalConfig.model_validate(
            {
                "schema_version": "1.0",
                "run": {"name": "test-dup-ids", "seed": 42},
                "dataset": {"type": "inline", "params": {}},
                "target": {"type": "echo", "params": {}},
                "scorers": [],
                "sinks": [],
            }
        )

        # Create an InlineDataset containing duplicate IDs
        ds = InlineDataset(
            items=[
                {"id": "dup", "inputs": {"input": "x"}},
                {"id": "dup", "inputs": {"input": "y"}},
            ]
        )

        # Simple mock target
        class MockTarget(TargetRunner):
            def run(self, item: EvalItem) -> Any:
                return "output"

        engine = EvalEngine(
            config,
            dataset=ds,
            target=MockTarget(),
            scorers=[],
            sinks=[],
        )

        with caplog.at_level(logging.WARNING):
            engine.run()

        assert any("Duplicate item ID detected in dataset: dup" in record.message for record in caplog.records)
