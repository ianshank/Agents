"""Opik access is hidden behind a narrow, SDK-optional seam.

The engine and sinks depend only on ``OpikClient``; the real Opik SDK is imported
lazily so the package installs and tests run with zero external dependencies.
``NullOpikClient`` records calls in memory for assertions and offline runs.
``SDKOpikClient`` wraps the real Opik SDK and handles batching, trace creation,
feedback score logging, and dataset item fetching.
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)

#: Shown to operators when an opt-in feature is requested but the SDK is missing.
INSTALL_HINT = "Install with: pip install opik"

ENV_OPIK_API_KEY = "OPIK_API_KEY"
ENV_OPIK_WORKSPACE = "OPIK_WORKSPACE"
ENV_OPIK_PROJECT_NAME = "OPIK_PROJECT_NAME"


def _ensure_ssl_bypass_if_windows() -> None:
    """Safely register HTTP client hook for Opik on Windows if SSL verification is disabled."""
    if os.name != "nt":
        return
    verify_ssl = os.environ.get("OPIK_VERIFY_SSL", "false").lower()
    if verify_ssl not in ("false", "0", "no"):
        return
    try:
        import ssl
        ssl._create_default_https_context = ssl._create_unverified_context
        from opik.hooks.httpx_client_hook import add_httpx_client_hook, HttpxClientHook, _httpx_client_hooks
        if not any(getattr(h, "_httpx_client_arguments", None) == {"verify": False} for h in _httpx_client_hooks):
            add_httpx_client_hook(
                HttpxClientHook(client_modifier=None, client_init_arguments={"verify": False})
            )
    except Exception as exc:
        logger.debug("Could not register Opik httpx SSL hook: %s", exc)


class OpikClient(ABC):
    """Narrow client interface that engine and sinks use to interact with Opik."""

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
    def log_item(
        self,
        *,
        run_id: str,
        item_id: str,
        input: Any,
        output: Any,
        expected: Any = None,
        scores: dict[str, float] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None: ...

    @abstractmethod
    def get_dataset_items(self, dataset_name: str) -> list[dict]: ...

    @abstractmethod
    def flush(self) -> None: ...

    def get_prompt(self, name: str, version: int | None = None, label: str | None = None) -> str | None:
        """Fetch prompt text from Opik Prompt Library."""
        return None


class NullOpikClient(OpikClient):
    """In-memory no-op client. Useful for offline runs and as a test double."""

    def __init__(self, dataset_items: dict[str, list[dict]] | None = None) -> None:
        self._datasets = dataset_items or {}
        self.scores: list[dict] = []
        self.items: list[dict] = []
        self.flushed = False

    def log_score(
        self,
        *,
        run_id: str,
        item_id: str,
        name: str,
        value: float,
        comment: str | None = None,
    ) -> None:
        self.scores.append(
            {
                "run_id": run_id,
                "item_id": item_id,
                "name": name,
                "value": value,
                "comment": comment,
            }
        )

    def log_item(
        self,
        *,
        run_id: str,
        item_id: str,
        input: Any,
        output: Any,
        expected: Any = None,
        scores: dict[str, float] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.items.append(
            {
                "run_id": run_id,
                "item_id": item_id,
                "input": input,
                "output": output,
                "expected": expected,
                "scores": scores or {},
                "metadata": metadata or {},
            }
        )

    def get_dataset_items(self, dataset_name: str) -> list[dict]:
        return list(self._datasets.get(dataset_name, []))

    def flush(self) -> None:
        self.flushed = True


class SDKOpikClient(OpikClient):
    """Adapter over the real ``opik`` SDK. Imported lazily."""

    def __init__(self, project_name: str = "eval-harness", **client_kwargs: Any) -> None:
        try:
            import opik
        except ImportError as exc:
            raise RuntimeError(
                f"The 'opik' package is required for SDKOpikClient. {INSTALL_HINT}"
            ) from exc

        _ensure_ssl_bypass_if_windows()

        self.project_name = project_name
        self._opik = opik
        self._client = opik.Opik(project_name=project_name, **client_kwargs)

    def log_score(
        self,
        *,
        run_id: str,
        item_id: str,
        name: str,
        value: float,
        comment: str | None = None,
    ) -> None:
        try:
            # Create a trace representing the score evaluation or log feedback score
            trace = self._client.trace(
                name=f"score-{name}",
                project_name=self.project_name,
                metadata={"run_id": run_id, "item_id": item_id},
            )
            trace.log_feedback_score(name=name, value=value, reason=comment)
        except Exception as exc:
            logger.warning("Failed to log score to Opik: %s", exc)

    def log_item(
        self,
        *,
        run_id: str,
        item_id: str,
        input: Any,
        output: Any,
        expected: Any = None,
        scores: dict[str, float] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        try:
            meta = {"run_id": run_id, "item_id": item_id}
            if metadata:
                meta.update(metadata)
            if expected is not None:
                meta["expected"] = str(expected)

            trace = self._client.trace(
                name=f"eval_item_{item_id}",
                project_name=self.project_name,
                input=input if isinstance(input, dict) else {"input": str(input)},
                output=output if isinstance(output, dict) else {"output": str(output)},
                metadata=meta,
            )
            if scores:
                for s_name, s_val in scores.items():
                    trace.log_feedback_score(name=s_name, value=s_val)
        except Exception as exc:
            logger.warning("Failed to log item trace to Opik: %s", exc)

    def get_dataset_items(self, dataset_name: str) -> list[dict]:
        try:
            dataset = self._client.get_dataset(dataset_name)
            items = []
            for item in getattr(dataset, "items", []):
                items.append(
                    {
                        "id": getattr(item, "id", None),
                        "inputs": getattr(item, "input", {}) or {},
                        "expected": getattr(item, "expected_output", None),
                        "metadata": getattr(item, "metadata", {}) or {},
                    }
                )
            return items
        except Exception as exc:
            logger.warning("Failed to fetch dataset '%s' from Opik: %s", dataset_name, exc)
            return []

    def get_prompt(self, name: str, version: int | None = None, label: str | None = None) -> str | None:
        try:
            prompt = self._client.get_prompt(name=name)
            if prompt and hasattr(prompt, "prompt"):
                return prompt.prompt
        except Exception as exc:
            logger.debug("Opik get_prompt failed for '%s': %s", name, exc)
        return None

    def flush(self) -> None:
        try:
            self._client.flush()
        except Exception as exc:
            logger.warning("Opik flush failed: %s", exc)


def build_client(
    enabled: bool = False,
    project_name: str | None = None,
) -> OpikClient:
    """Build an Opik client from config / environment parameters.

    Returns ``NullOpikClient`` when ``enabled`` is False or ``opik`` is absent/unconfigured.
    """
    if not enabled:
        return NullOpikClient()
    proj = project_name or os.environ.get(ENV_OPIK_PROJECT_NAME, "eval-harness")
    try:
        return SDKOpikClient(project_name=proj)
    except Exception as exc:
        logger.warning("Failed to build SDKOpikClient, falling back to NullOpikClient: %s", exc)
        return NullOpikClient()
