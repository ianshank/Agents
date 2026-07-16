"""BrainTrust experiment export — hidden behind a narrow, SDK-optional seam.

Mirrors the ``phoenix_client`` design: the real ``braintrust`` package is imported
lazily, so this package installs and the offline suite runs with zero external
dependencies. ``NullBrainTrustClient`` records calls in memory for assertions and
offline runs; ``SDKBrainTrustClient`` wraps a real BrainTrust *experiment* handle.

Unlike the Phoenix/Langfuse score seam (one call per *score*), BrainTrust's native
write-path is per *item*: a single ``experiment.log(input=, output=, expected=,
scores={name: value}, metadata=)`` row carries the whole item plus all its scores.
So the narrow method here is :meth:`BrainTrustClient.log_item`, and the ``braintrust``
result sink folds each item's ``ScoreResult``s into one ``scores`` dict.

Every entry point fails safe: if BrainTrust is absent or the network is unreachable,
export silently degrades to a no-op and the eval run proceeds unaffected — the same
contract as ``SDKPhoenixScoreClient``. Credentials are read by the SDK from the
environment (``BRAINTRUST_API_KEY``; optional ``BRAINTRUST_API_URL`` for self-hosted
stacks), never hardcoded here.

Version note: ``braintrust`` is pre-1.0, so this seam binds only to the narrowest,
most-documented surface — ``braintrust.init(project=, experiment=)`` and
``experiment.log(...)`` with named 0..1 scores. Newer/internal modules are avoided.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)

#: Shown to operators when export is requested but the SDK is missing.
INSTALL_HINT = "Install with: pip install 'langfuse-eval-harness[braintrust]'"


class BrainTrustClient(ABC):
    """Narrow client the ``braintrust`` sink logs eval items through."""

    @abstractmethod
    def log_item(
        self,
        *,
        run_id: str,
        item_id: str,
        input: Any,
        output: Any,
        expected: Any = None,
        scores: dict[str, float],
        metadata: dict[str, Any] | None = None,
    ) -> None: ...

    @abstractmethod
    def flush(self) -> None: ...


class NullBrainTrustClient(BrainTrustClient):
    """In-memory no-op client. Used offline and as a test double (records calls)."""

    def __init__(self) -> None:
        self.items: list[dict] = []
        self.flushed = False

    def log_item(
        self,
        *,
        run_id: str,
        item_id: str,
        input: Any,
        output: Any,
        expected: Any = None,
        scores: dict[str, float],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.items.append(
            {
                "run_id": run_id,
                "item_id": item_id,
                "input": input,
                "output": output,
                "expected": expected,
                "scores": scores,
                "metadata": metadata,
            }
        )

    def flush(self) -> None:
        self.flushed = True


class SDKBrainTrustClient(BrainTrustClient):
    """Logs each eval item to a BrainTrust experiment via ``experiment.log(...)``.

    The experiment handle is injected (resolved by :func:`build_client`), which keeps
    this class free of import side effects and trivially testable against a fake. Fails
    safe: a logging error is recorded, never raised, so telemetry can't break a run.
    """

    def __init__(self, experiment: Any) -> None:
        self._experiment = experiment

    def log_item(
        self,
        *,
        run_id: str,
        item_id: str,
        input: Any,
        output: Any,
        expected: Any = None,
        scores: dict[str, float],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        try:
            self._experiment.log(
                id=item_id,
                input=input,
                output=output,
                expected=expected,
                scores=scores,
                metadata={**(metadata or {}), "run_id": run_id},
            )
        except Exception as exc:
            logger.error("BrainTrust log_item failed for item %s: %s", item_id, exc)

    def flush(self) -> None:
        try:
            self._experiment.flush()
        except Exception as exc:
            logger.error("BrainTrust flush failed: %s", exc)


def _init_experiment(project_name: str, experiment_name: str) -> Any:
    """Return a live BrainTrust experiment handle.

    Credentials come from the environment (``BRAINTRUST_API_KEY`` / ``BRAINTRUST_API_URL``),
    read by the SDK itself — nothing is passed or hardcoded here. Raises ``ImportError`` if the
    SDK is absent, or the SDK's own error if ``init`` fails; :func:`build_client` maps each to
    the no-op client, distinguishing "not installed" from "init failed" in its logging.
    """
    import braintrust

    # Narrowest documented surface: init() opens/creates an experiment in a project.
    return braintrust.init(project=project_name, experiment=experiment_name)


def build_client(*, enabled: bool, project_name: str, experiment_name: str) -> BrainTrustClient:
    """Return the client for the ``braintrust`` sink.

    ``NullBrainTrustClient`` unless ``enabled`` *and* the BrainTrust SDK is importable *and* the
    experiment initializes. Fails safe with a message that distinguishes the two failure modes:
    a missing SDK warns with the install hint, while a failed ``init`` (e.g. a bad
    ``BRAINTRUST_API_KEY``) logs the underlying error and silently no-ops — it does NOT suggest
    installing an SDK that is already present.
    """
    if not enabled:
        return NullBrainTrustClient()
    try:
        import braintrust  # noqa: F401 — presence gate; the real init lives in _init_experiment
    except ImportError:
        logger.warning(
            "BrainTrust export requested but the 'braintrust' SDK is not installed; using no-op. %s",
            INSTALL_HINT,
        )
        return NullBrainTrustClient()
    try:
        experiment = _init_experiment(project_name, experiment_name)
    except Exception as exc:
        logger.error("braintrust.init(project=%s) failed; export disabled (using no-op): %s", project_name, exc)
        return NullBrainTrustClient()
    return SDKBrainTrustClient(experiment)
