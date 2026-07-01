"""Arize Phoenix observability — hidden behind a narrow, SDK-optional seam.

Mirrors the ``langfuse_client`` design: the real Phoenix packages
(``arize-phoenix-otel`` + ``openinference-instrumentation-*``) are imported lazily,
so this package installs and the offline suite runs with zero external dependencies.

Two independent concerns live here, kept deliberately separate (they map to two
different Phoenix distributions and two different lifecycles):

* **Tracing** (``configure_tracing`` / ``phoenix_observe``) — process-global
  OpenTelemetry/OpenInference auto-instrumentation emitted to a self-hosted Phoenix
  collector. The endpoint and API key come from the environment
  (``PHOENIX_COLLECTOR_ENDPOINT`` / ``PHOENIX_API_KEY``), never hardcoded.
* **Score export** (``PhoenixScoreClient`` and friends) — a narrow per-run sink
  client used by the ``phoenix`` result sink. See :mod:`eval_harness.sinks`.

Every entry point fails safe: if Phoenix is absent or the collector is unreachable,
the feature silently degrades and the eval run proceeds unaffected — the same
contract as ``SDKLangfuseClient``.
"""

from __future__ import annotations

import functools
import logging
import os
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .config.models import PhoenixConfig

logger = logging.getLogger(__name__)

#: Shown to operators when an opt-in feature is requested but the SDK is missing.
INSTALL_HINT = "Install with: pip install 'langfuse-eval-harness[phoenix]'"

#: OTLP collector endpoint env var (read here; the *value* is never stored in config).
ENV_COLLECTOR_ENDPOINT = "PHOENIX_COLLECTOR_ENDPOINT"


def configure_tracing(config: PhoenixConfig | None) -> Any | None:
    """Configure Phoenix/OpenInference tracing from ``config``.

    Returns the OpenTelemetry tracer provider on success, or ``None`` when tracing is
    disabled, the SDK is not installed, or the collector call fails. Never raises —
    a telemetry problem must not break an evaluation run.
    """
    if config is None or not config.enabled or not config.tracing:
        return None
    try:
        from phoenix.otel import register
    except ImportError:
        logger.warning("arize-phoenix-otel is not installed; Phoenix tracing disabled. %s", INSTALL_HINT)
        return None

    kwargs: dict[str, Any] = {
        "project_name": config.project_name,
        "auto_instrument": config.auto_instrument,
        "batch": config.batch,
    }
    endpoint = os.environ.get(ENV_COLLECTOR_ENDPOINT)
    if endpoint:
        kwargs["endpoint"] = endpoint
    try:
        provider = register(**kwargs)
        logger.debug(
            "Phoenix tracing configured (project=%s, endpoint=%s, auto_instrument=%s)",
            config.project_name,
            endpoint or "<sdk-default>",
            config.auto_instrument,
        )
        return provider
    except Exception as exc:
        logger.error("phoenix.otel.register() failed; tracing disabled: %s", exc)
        return None


def _otel_tracer() -> Any | None:
    """Return an OpenTelemetry tracer iff Phoenix *and* OTel are importable, else ``None``."""
    try:
        from opentelemetry import trace
        from phoenix.otel import register  # noqa: F401 - import is a presence gate, not a call
    except ImportError:
        return None
    return trace.get_tracer(__name__)


def phoenix_observe(*decorator_args: Any, **decorator_kwargs: Any) -> Any:
    """No-op-fallback span decorator, mirroring langfuse ``observe()``.

    Opens an OpenTelemetry span around the callable when Phoenix + OTel are installed;
    a transparent passthrough otherwise. Supports both ``@phoenix_observe`` and
    ``@phoenix_observe(name=...)``.
    """

    def _decorate(func: Callable[..., Any]) -> Callable[..., Any]:
        tracer = _otel_tracer()
        if tracer is None:
            return func
        span_name = decorator_kwargs.get("name") or getattr(func, "__name__", "span")

        @functools.wraps(func)
        def _wrapped(*args: Any, **kwargs: Any) -> Any:
            with tracer.start_as_current_span(span_name):
                return func(*args, **kwargs)

        return _wrapped

    # Bare form: @phoenix_observe  (first positional arg is the function itself)
    if len(decorator_args) == 1 and callable(decorator_args[0]) and not decorator_kwargs:
        return _decorate(decorator_args[0])
    return _decorate


# --------------------------------------------------------------------------- #
# Score export — the narrow client behind the ``phoenix`` result sink.
#
# This is intentionally a *different* seam from tracing: it maps to the per-run
# score-logging concern (mirroring the subset of ``LangfuseClient`` that
# ``LangfuseSink`` uses), not to process-global instrumentation. The SDK impl
# emits each score as an OpenTelemetry span carrying ``eval.*`` attributes, using
# only the stable ``arize-phoenix-otel`` surface — so it needs no version-pinned
# ``arize-phoenix-client`` API and stays correct across Phoenix releases.
# --------------------------------------------------------------------------- #

#: OTLP attribute keys for exported eval scores (single-sourced, not scattered literals).
_ATTR_RUN_ID = "eval.run_id"
_ATTR_ITEM_ID = "eval.item_id"
_ATTR_SCORE_NAME = "eval.score.name"
_ATTR_SCORE_VALUE = "eval.score.value"
_ATTR_SCORE_COMMENT = "eval.score.comment"


class PhoenixScoreClient(ABC):
    """Narrow client the ``phoenix`` sink logs eval scores through."""

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
    def flush(self) -> None: ...


class NullPhoenixScoreClient(PhoenixScoreClient):
    """In-memory no-op client. Used offline and as a test double (records calls)."""

    def __init__(self) -> None:
        self.scores: list[dict] = []
        self.flushed = False

    def log_score(self, *, run_id, item_id, name, value, comment=None) -> None:
        self.scores.append({"run_id": run_id, "item_id": item_id, "name": name, "value": value, "comment": comment})

    def flush(self) -> None:
        self.flushed = True


class SDKPhoenixScoreClient(PhoenixScoreClient):
    """Emits each eval score as an OpenTelemetry span with ``eval.*`` attributes.

    The tracer is injected (resolved by :func:`build_score_client`), which keeps this
    class free of import side effects and trivially testable. Fails safe: a telemetry
    error is logged, never raised.
    """

    def __init__(self, tracer: Any) -> None:
        self._tracer = tracer

    def log_score(self, *, run_id, item_id, name, value, comment=None) -> None:
        try:
            with self._tracer.start_as_current_span(f"eval.score.{name}") as span:
                span.set_attribute(_ATTR_RUN_ID, run_id)
                span.set_attribute(_ATTR_ITEM_ID, item_id)
                span.set_attribute(_ATTR_SCORE_NAME, name)
                span.set_attribute(_ATTR_SCORE_VALUE, float(value))
                if comment:
                    span.set_attribute(_ATTR_SCORE_COMMENT, comment)
        except Exception as exc:
            logger.error("Phoenix log_score failed for item %s: %s", item_id, exc)

    def flush(self) -> None:
        # Spans are flushed by the tracer provider's batch processor; nothing per-call.
        logger.debug("Phoenix score client flush (spans flushed by the OTel processor).")


def build_score_client(*, enabled: bool) -> PhoenixScoreClient:
    """Return the score client for the ``phoenix`` sink.

    ``NullPhoenixScoreClient`` unless ``enabled`` and the Phoenix SDK is importable.
    Fails safe: if export is requested but the SDK is absent, logs a warning and returns
    the no-op client so the run still completes.
    """
    if not enabled:
        return NullPhoenixScoreClient()
    tracer = _otel_tracer()
    if tracer is None:
        logger.warning(
            "Phoenix score export requested but arize-phoenix-otel is not installed; " "using no-op. %s", INSTALL_HINT
        )
        return NullPhoenixScoreClient()
    return SDKPhoenixScoreClient(tracer)
