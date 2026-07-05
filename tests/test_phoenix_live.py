"""Live Phoenix validation — ``@pytest.mark.integration``.

These exercise the REAL arize-phoenix-* packages against a running Phoenix collector
and a real model, so they run only where the ``[phoenix]`` / ``[phoenix-evals]`` extras
are installed AND the relevant endpoint/secret env vars are present (e.g. the
``phoenix-live`` GitHub workflow). They **skip cleanly** everywhere else — including the
air-gapped offline suite, where neither SDK is importable.

All identifiers that would collide across reruns on the same collector — project name,
span name, judge name — are read from the environment with sensible defaults, so a fresh
run can be namespaced without editing this file. See the workflow at
``.github/workflows/phoenix-live.yml`` for the CI values.
"""

from __future__ import annotations

import logging
import os

import pytest

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.integration

# Environment-driven overrides — every default matches the workflow's expectations, but
# a local operator can namespace a run without touching source or the workflow file.
ENV_COLLECTOR_ENDPOINT = "PHOENIX_COLLECTOR_ENDPOINT"
ENV_OPENAI_API_KEY = "OPENAI_API_KEY"
ENV_PROJECT = "PHOENIX_LIVE_PROJECT"
ENV_SPAN_NAME = "PHOENIX_LIVE_SPAN_NAME"
ENV_JUDGE_NAME = "PHOENIX_LIVE_JUDGE_NAME"
ENV_EVAL_MODEL = "PHOENIX_EVAL_MODEL"

DEFAULT_PROJECT = "phoenix-live-smoke"
DEFAULT_SPAN_NAME = "phoenix-live-smoke-span"
DEFAULT_JUDGE_NAME = "phoenix-live-correctness"
DEFAULT_EVAL_MODEL = "gpt-4o-mini"


def test_configure_tracing_live_registers_and_traces() -> None:
    """Item 1 — configure_tracing() registers a real provider and a span runs through it."""
    pytest.importorskip("phoenix.otel", reason="arize-phoenix-otel not installed")
    endpoint = os.environ.get(ENV_COLLECTOR_ENDPOINT)
    if not endpoint:
        pytest.skip(f"{ENV_COLLECTOR_ENDPOINT} not set")

    from eval_harness.config.models import PhoenixConfig
    from eval_harness.phoenix_client import configure_tracing, phoenix_observe

    project = os.environ.get(ENV_PROJECT, DEFAULT_PROJECT)
    span_name = os.environ.get(ENV_SPAN_NAME, DEFAULT_SPAN_NAME)
    logger.info(
        "phoenix-live tracing: endpoint=%s project=%s span=%s",
        endpoint,
        project,
        span_name,
    )

    provider = configure_tracing(PhoenixConfig(enabled=True, project_name=project))
    assert provider is not None  # a real tracer provider from phoenix.otel.register()

    @phoenix_observe(name=span_name)
    def _work() -> int:
        return 21 + 21

    assert _work() == 42

    flush = getattr(provider, "force_flush", None)  # best-effort: push the span to the collector
    if callable(flush):
        logger.debug("force_flush available; pushing span batch to collector")
        flush()


def test_phoenix_eval_judge_live_returns_scored_verdict() -> None:
    """Item 3 — PhoenixEvalJudge classifies against a real model via the 0.29 API."""
    pytest.importorskip("phoenix.evals", reason="arize-phoenix-evals not installed")
    if not os.environ.get(ENV_OPENAI_API_KEY):
        pytest.skip(f"{ENV_OPENAI_API_KEY} not set")

    from eval_harness.judges import PhoenixEvalJudge

    model = os.environ.get(ENV_EVAL_MODEL, DEFAULT_EVAL_MODEL)
    judge_name = os.environ.get(ENV_JUDGE_NAME, DEFAULT_JUDGE_NAME)
    logger.info("phoenix-live evals: model=%s judge=%s", model, judge_name)

    judge = PhoenixEvalJudge(
        model=model,
        prompt_template="Is the following statement correct? {prompt}\nAnswer CORRECT or INCORRECT.",
        choices={"CORRECT": 1.0, "INCORRECT": 0.0},
        name=judge_name,
    )
    verdict = judge.evaluate("2 + 2 = 4")
    assert 0.0 <= verdict.score <= 1.0
    assert verdict.raw.get("label") in {"CORRECT", "INCORRECT", None}
