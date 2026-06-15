"""Langfuse access is hidden behind a narrow interface.

The engine and sinks depend only on ``LangfuseClient``; the real SDK is imported
lazily so the package installs and tests run with zero external dependencies.
``NullLangfuseClient`` records calls in memory for assertions and offline runs.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class LangfuseClient(ABC):
    @abstractmethod
    def get_dataset_items(self, dataset_name: str) -> list[dict]:
        ...

    @abstractmethod
    def log_score(
        self,
        *,
        run_id: str,
        item_id: str,
        name: str,
        value: float,
        comment: Optional[str] = None,
    ) -> None:
        ...

    @abstractmethod
    def flush(self) -> None:
        ...


class NullLangfuseClient(LangfuseClient):
    """In-memory no-op client. Useful for offline runs and as a test double."""

    def __init__(self, dataset_items: Optional[dict[str, list[dict]]] = None) -> None:
        self._datasets = dataset_items or {}
        self.scores: list[dict] = []
        self.flushed = False

    def get_dataset_items(self, dataset_name: str) -> list[dict]:
        return list(self._datasets.get(dataset_name, []))

    def log_score(self, *, run_id, item_id, name, value, comment=None) -> None:
        self.scores.append(
            {
                "run_id": run_id,
                "item_id": item_id,
                "name": name,
                "value": value,
                "comment": comment,
            }
        )

    def flush(self) -> None:
        self.flushed = True


class SDKLangfuseClient(LangfuseClient):  # pragma: no cover - requires network/SDK
    """Adapter over the real ``langfuse`` SDK. Imported lazily."""

    def __init__(self, **client_kwargs: Any) -> None:
        try:
            from langfuse import Langfuse
        except ImportError as exc:
            raise RuntimeError(
                "The 'langfuse' package is required for SDKLangfuseClient. "
                "Install with: pip install 'langfuse-eval-harness[langfuse]'"
            ) from exc
        self._lf = Langfuse(**client_kwargs)

    def get_dataset_items(self, dataset_name: str) -> list[dict]:
        dataset = self._lf.get_dataset(dataset_name)
        items = []
        for it in dataset.items:
            items.append(
                {
                    "id": getattr(it, "id", None),
                    "inputs": getattr(it, "input", {}) or {},
                    "expected": getattr(it, "expected_output", None),
                    "metadata": getattr(it, "metadata", {}) or {},
                }
            )
        return items

    def log_score(self, *, run_id, item_id, name, value, comment=None) -> None:
        self._lf.create_score(
            name=name,
            value=value,
            comment=comment,
            trace_id=item_id,
            metadata={"run_id": run_id},
        )

    def flush(self) -> None:
        self._lf.flush()
