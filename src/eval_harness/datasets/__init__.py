"""Built-in dataset sources."""

from __future__ import annotations

import csv
import json
import logging
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ..core.interfaces import DatasetSource
from ..core.types import EvalItem
from ..langfuse_client import LangfuseClient
from ..plugins import DATASETS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_item(record: dict, fallback_id: int) -> EvalItem:
    """Convert a raw dict record into an :class:`EvalItem`."""
    return EvalItem(
        id=str(record.get("id", fallback_id)),
        inputs=record.get("inputs", {}),
        expected=record.get("expected"),
        metadata=record.get("metadata", {}) or {},
    )


def _validate_dataset_path(path: str | Path, *, allow_absolute: bool = False) -> Path:
    """Validate and resolve a dataset file path.

    Rejects path traversal attempts and optionally restricts to relative paths.
    Respects ``DATA_ROOT`` env var for constraining file access.
    """
    resolved = Path(path).resolve()
    data_root_env = os.environ.get("DATA_ROOT")

    if data_root_env:
        data_root = Path(data_root_env).resolve()
        if not str(resolved).startswith(str(data_root)):
            raise ValueError(f"Dataset path {resolved} is outside DATA_ROOT {data_root}")

    # Reject obvious traversal in the raw string
    raw = str(path)
    if (".." in raw.split(os.sep) or ".." in raw.split("/")) and not data_root_env:
        raise ValueError(
            f"Path traversal ('..') detected in dataset path: {raw}. "
            "Set DATA_ROOT env var to explicitly allow controlled access."
        )

    if not allow_absolute and Path(path).is_absolute() and not data_root_env:
        logger.warning(
            "Absolute dataset path %s used without DATA_ROOT. Consider setting DATA_ROOT for path confinement.",
            path,
        )

    return resolved


# ---------------------------------------------------------------------------
# Built-in dataset sources
# ---------------------------------------------------------------------------


@DATASETS.register("inline")
class InlineDataset(DatasetSource):
    """Dataset defined directly in the YAML config as inline items."""

    def __init__(self, items: list[dict] | None = None):
        self.items = items or []

    def load(self) -> Iterable[EvalItem]:
        """Yield :class:`EvalItem` instances from the inline list."""
        return [_to_item(rec, i) for i, rec in enumerate(self.items)]


@DATASETS.register("jsonl")
class JsonlDataset(DatasetSource):
    """Dataset loaded from a JSON Lines file."""

    def __init__(self, path: str):
        self.path = Path(path)

    def load(self) -> Iterable[EvalItem]:
        """Parse each non-empty line as JSON and yield :class:`EvalItem`."""
        items = []
        for i, line in enumerate(self.path.read_text(encoding="utf-8").splitlines()):
            line = line.strip()
            if line:
                items.append(_to_item(json.loads(line), i))
        return items


@DATASETS.register("langfuse")
class LangfuseDataset(DatasetSource):
    """Pulls a dataset from Langfuse. The client is injected by the engine."""

    def __init__(self, dataset_name: str):
        self.dataset_name = dataset_name
        self._client: LangfuseClient | None = None

    def attach_client(self, client: LangfuseClient) -> None:
        """Attach the Langfuse client for dataset retrieval."""
        self._client = client

    def load(self) -> Iterable[EvalItem]:
        """Fetch dataset items from Langfuse and yield :class:`EvalItem`."""
        if self._client is None:
            raise RuntimeError("LangfuseDataset has no client attached")
        records = self._client.get_dataset_items(self.dataset_name)
        return [_to_item(rec, i) for i, rec in enumerate(records)]


@DATASETS.register("csv", aliases=("csv_file",))
class CsvDataset(DatasetSource):
    """Dataset loaded from a CSV file with configurable column mappings.

    Parameters
    ----------
    path:
        Path to the CSV file.
    id_column:
        Column name to use as the item id. Defaults to ``"id"``.
    input_columns:
        List of column names to include in ``inputs``. Defaults to ``["input"]``.
    expected_column:
        Column name for the expected value. Defaults to ``"expected"``.
    metadata_columns:
        Optional list of column names to include in ``metadata``.
        If ``None``, no metadata columns are extracted.
    encoding:
        File encoding. Defaults to ``"utf-8-sig"`` (handles BOM).
    """

    def __init__(
        self,
        path: str,
        id_column: str = "id",
        input_columns: list[str] | None = None,
        expected_column: str = "expected",
        metadata_columns: list[str] | None = None,
        encoding: str = "utf-8-sig",
    ) -> None:
        self.path = _validate_dataset_path(path)
        self.id_column = id_column
        self.input_columns = input_columns if input_columns is not None else ["input"]
        self.expected_column = expected_column
        self.metadata_columns = metadata_columns
        self.encoding = encoding

    def load(self) -> Iterable[EvalItem]:
        """Read the CSV and yield :class:`EvalItem` for each row."""
        items: list[EvalItem] = []
        with open(self.path, newline="", encoding=self.encoding) as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames is None:
                return items

            # Validate required columns exist in the header
            header_set = set(reader.fieldnames)
            missing: list[str] = []
            for col in self.input_columns:
                if col not in header_set:
                    missing.append(col)
            if missing:
                raise ValueError(
                    f"CSV {self.path} is missing required input column(s): {missing}. "
                    f"Available columns: {sorted(header_set)}"
                )

            for i, row in enumerate(reader):
                item_id = str(row.get(self.id_column, i))
                inputs: dict[str, Any] = {col: row[col] for col in self.input_columns}
                expected = row.get(self.expected_column)
                metadata: dict[str, Any] = {}
                if self.metadata_columns:
                    metadata = {col: row.get(col) for col in self.metadata_columns}
                items.append(
                    EvalItem(
                        id=item_id,
                        inputs=inputs,
                        expected=expected,
                        metadata=metadata,
                    )
                )
        return items


@DATASETS.register("parquet", aliases=("parquet_file",))
class ParquetDataset(DatasetSource):
    """Dataset loaded from a Parquet file with configurable column mappings.

    Requires ``pyarrow`` to be installed (optional dependency).

    Parameters
    ----------
    path:
        Path to the Parquet file.
    id_column:
        Column name to use as the item id. Defaults to ``"id"``.
    input_columns:
        List of column names to include in ``inputs``. Defaults to ``["input"]``.
    expected_column:
        Column name for the expected value. Defaults to ``"expected"``.
    metadata_columns:
        Optional list of column names to include in ``metadata``.
    """

    def __init__(
        self,
        path: str,
        id_column: str = "id",
        input_columns: list[str] | None = None,
        expected_column: str = "expected",
        metadata_columns: list[str] | None = None,
    ) -> None:
        self.path = _validate_dataset_path(path)
        self.id_column = id_column
        self.input_columns = input_columns if input_columns is not None else ["input"]
        self.expected_column = expected_column
        self.metadata_columns = metadata_columns

    def load(self) -> Iterable[EvalItem]:
        """Read the Parquet file and yield :class:`EvalItem` for each row."""
        try:
            import pyarrow.parquet as pq
        except ImportError as exc:
            raise ImportError("pyarrow is required for ParquetDataset. Install it with: pip install pyarrow") from exc

        table = pq.read_table(str(self.path))
        columns = set(table.column_names)

        # Validate required columns
        missing = [c for c in self.input_columns if c not in columns]
        if missing:
            raise ValueError(
                f"Parquet {self.path} is missing required input column(s): {missing}. "
                f"Available columns: {sorted(columns)}"
            )

        items: list[EvalItem] = []
        rows = table.to_pydict()  # {col_name: [values]}
        n_rows = table.num_rows

        for i in range(n_rows):
            item_id = str(rows[self.id_column][i]) if self.id_column in columns else str(i)
            inputs: dict[str, Any] = {col: rows[col][i] for col in self.input_columns}
            expected = rows[self.expected_column][i] if self.expected_column in columns else None
            metadata: dict[str, Any] = {}
            if self.metadata_columns:
                metadata = {col: rows[col][i] for col in self.metadata_columns if col in columns}
            items.append(
                EvalItem(
                    id=item_id,
                    inputs=inputs,
                    expected=expected,
                    metadata=metadata,
                )
            )
        return items
