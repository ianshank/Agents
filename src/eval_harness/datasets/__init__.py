"""Built-in dataset sources."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Optional

from ..core.interfaces import DatasetSource
from ..core.types import EvalItem
from ..langfuse_client import LangfuseClient
from ..plugins import DATASETS


def _to_item(record: dict, fallback_id: int) -> EvalItem:
    return EvalItem(
        id=str(record.get("id", fallback_id)),
        inputs=record.get("inputs", {}),
        expected=record.get("expected"),
        metadata=record.get("metadata", {}) or {},
    )


@DATASETS.register("inline")
class InlineDataset(DatasetSource):
    def __init__(self, items: Optional[list[dict]] = None):
        self.items = items or []

    def load(self) -> Iterable[EvalItem]:
        return [_to_item(rec, i) for i, rec in enumerate(self.items)]


@DATASETS.register("jsonl")
class JsonlDataset(DatasetSource):
    def __init__(self, path: str):
        self.path = Path(path)

    def load(self) -> Iterable[EvalItem]:
        items = []
        for i, line in enumerate(self.path.read_text().splitlines()):
            line = line.strip()
            if line:
                items.append(_to_item(json.loads(line), i))
        return items


@DATASETS.register("langfuse")
class LangfuseDataset(DatasetSource):
    """Pulls a dataset from Langfuse. The client is injected by the engine."""

    def __init__(self, dataset_name: str):
        self.dataset_name = dataset_name
        self._client: Optional[LangfuseClient] = None

    def attach_client(self, client: LangfuseClient) -> None:
        self._client = client

    def load(self) -> Iterable[EvalItem]:
        if self._client is None:
            raise RuntimeError("LangfuseDataset has no client attached")
        records = self._client.get_dataset_items(self.dataset_name)
        return [_to_item(rec, i) for i, rec in enumerate(records)]
