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
    def link_dataset_item(
        self,
        *,
        item_id: str,
        trace_id: str,
        run_name: str,
        run_description: Optional[str] = None,
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

    def link_dataset_item(
        self,
        *,
        item_id: str,
        trace_id: str,
        run_name: str,
        run_description: Optional[str] = None,
    ) -> None:
        pass

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
        
        # Inject defaults if not present in env or kwargs
        import os
        os.environ.setdefault("LANGFUSE_SECRET_KEY", "sk-lf-e220d788-d2e0-4e82-bbde-6d1a57ba149f")
        os.environ.setdefault("LANGFUSE_PUBLIC_KEY", "pk-lf-ad617cfc-ce1b-4c23-8c76-7868605ee6f1")
        os.environ.setdefault("LANGFUSE_BASE_URL", "https://us.cloud.langfuse.com")
        
        # Explicit keys check in client_kwargs
        if "secret_key" not in client_kwargs:
            client_kwargs["secret_key"] = os.environ["LANGFUSE_SECRET_KEY"]
        if "public_key" not in client_kwargs:
            client_kwargs["public_key"] = os.environ["LANGFUSE_PUBLIC_KEY"]
        if "host" not in client_kwargs:
            client_kwargs["host"] = os.environ["LANGFUSE_BASE_URL"]

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

    def link_dataset_item(
        self,
        *,
        item_id: str,
        trace_id: str,
        run_name: str,
        run_description: Optional[str] = None,
    ) -> None:
        try:
            self._lf.api.dataset_run_items.create(
                run_name=run_name,
                run_description=run_description,
                dataset_item_id=item_id,
                trace_id=trace_id,
            )
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error(f"Failed to link trace to dataset item: {exc}")

    def flush(self) -> None:
        self._lf.flush()


def observe(*decorator_args: Any, **decorator_kwargs: Any) -> Any:
    """Graceful wrapper around langfuse.decorators.observe.
    
    If the langfuse SDK is not installed, it acts as a transparent no-op decorator.
    """
    try:
        from langfuse.decorators import observe as lf_observe
        return lf_observe(*decorator_args, **decorator_kwargs)
    except ImportError:
        def no_op_decorator(func: Any) -> Any:
            return func
        return no_op_decorator


class SafeLangfuseContext:
    def get_current_trace_id(self) -> Optional[str]:
        try:
            from langfuse.decorators import langfuse_context
            return langfuse_context.get_current_trace_id()  # type: ignore[no-any-return]
        except ImportError:
            return None

langfuse_context = SafeLangfuseContext()
