"""Langfuse access is hidden behind a narrow interface.

The engine and sinks depend only on ``LangfuseClient``; the real SDK is imported
lazily so the package installs and tests run with zero external dependencies.
``NullLangfuseClient`` records calls in memory for assertions and offline runs.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LangfuseClient(ABC):
    @abstractmethod
    def get_dataset_items(self, dataset_name: str) -> list[dict]: ...

    @abstractmethod
    def log_score(
        self,
        *,
        run_id: str,
        item_id: str,
        name: str,
        value: float,
        comment: str | None = None,
    ) -> None: ...

    @abstractmethod
    def link_dataset_item(
        self,
        *,
        item_id: str,
        trace_id: str,
        run_name: str,
        run_description: str | None = None,
    ) -> None: ...

    @abstractmethod
    def flush(self) -> None: ...

    def get_prompt(self, name: str, version: int | None = None, label: str | None = None) -> str | None:
        """Fetch a managed prompt's text from the Langfuse prompt registry (F-026).

        Non-abstract with a ``None`` default so existing subclasses keep working
        and the offline path needs no Langfuse. Returns ``None`` when the prompt
        is unavailable; callers fall back to the config-supplied text.
        """
        return None


class NullLangfuseClient(LangfuseClient):
    """In-memory no-op client. Useful for offline runs and as a test double."""

    def __init__(self, dataset_items: dict[str, list[dict]] | None = None) -> None:
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
        run_description: str | None = None,
    ) -> None:
        pass

    def flush(self) -> None:
        self.flushed = True


class SDKLangfuseClient(LangfuseClient):
    """Adapter over the real ``langfuse`` SDK. Imported lazily."""

    def __init__(self, **client_kwargs: Any) -> None:
        try:
            from langfuse import Langfuse
        except ImportError as exc:
            raise RuntimeError(
                "The 'langfuse' package is required for SDKLangfuseClient. "
                "Install with: pip install 'langfuse-eval-harness[langfuse]'"
            ) from exc

        import os

        _required_env = {
            "LANGFUSE_SECRET_KEY": "secret_key",
            "LANGFUSE_PUBLIC_KEY": "public_key",
            "LANGFUSE_BASE_URL": "host",
        }
        for env_var, kwarg_name in _required_env.items():
            if kwarg_name not in client_kwargs:
                value = os.environ.get(env_var)
                if value:
                    client_kwargs[kwarg_name] = value

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
        run_description: str | None = None,
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

            logging.getLogger(__name__).error("Failed to link trace to dataset item: %s", exc)

    def flush(self) -> None:
        self._lf.flush()

    def get_prompt(self, name: str, version: int | None = None, label: str | None = None) -> str | None:
        """Fetch a managed prompt's text from Langfuse (F-026).

        Fails safe: any SDK/network error returns ``None`` so the caller falls
        back to the config-supplied text (mirrors the no-op tracing fallback).
        """
        try:
            kwargs: dict[str, Any] = {}
            if version is not None:
                kwargs["version"] = version
            if label is not None:
                kwargs["label"] = label
            prompt = self._lf.get_prompt(name, **kwargs)
            text = getattr(prompt, "prompt", None)
            return text if isinstance(text, str) else None
        except Exception as exc:
            import logging

            logging.getLogger(__name__).warning("Langfuse get_prompt(%r) failed: %s", name, exc)
            return None


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
    def get_current_trace_id(self) -> str | None:
        try:
            from langfuse.decorators import langfuse_context

            return langfuse_context.get_current_trace_id()  # type: ignore[no-any-return]
        except ImportError:
            return None


langfuse_context = SafeLangfuseContext()
