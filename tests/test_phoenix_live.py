"""Live Phoenix validation — ``@pytest.mark.integration``.

These exercise the REAL arize-phoenix-* packages against a running Phoenix collector
and a real model, so they run only where the ``[phoenix]`` / ``[phoenix-evals]`` extras
are installed AND the relevant endpoint/secret env vars are present (e.g. the
``phoenix-live`` GitHub workflow). They **skip cleanly** everywhere else — including the
air-gapped offline suite, where neither SDK is importable.
"""

from __future__ import annotations

import importlib.util
import os

import pytest

pytestmark = pytest.mark.integration


def _installed(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except ModuleNotFoundError:
        return False


@pytest.mark.skipif(not _installed("phoenix.otel"), reason="arize-phoenix-otel not installed")
def test_configure_tracing_live_registers_and_traces() -> None:
    """Item 1 — configure_tracing() registers a real provider and a span runs through it."""
    if not os.environ.get("PHOENIX_COLLECTOR_ENDPOINT"):
        pytest.skip("PHOENIX_COLLECTOR_ENDPOINT not set")

    from eval_harness.config.models import PhoenixConfig
    from eval_harness.phoenix_client import configure_tracing, phoenix_observe

    provider = configure_tracing(PhoenixConfig(enabled=True, project_name="phoenix-live-smoke"))
    assert provider is not None  # a real tracer provider from phoenix.otel.register()

    @phoenix_observe(name="phoenix-live-smoke-span")
    def _work() -> int:
        return 21 + 21

    assert _work() == 42

    flush = getattr(provider, "force_flush", None)  # best-effort: push the span to the collector
    if callable(flush):
        flush()


@pytest.mark.skipif(not _installed("phoenix.evals"), reason="arize-phoenix-evals not installed")
def test_phoenix_eval_judge_live_returns_scored_verdict() -> None:
    """Item 3 — PhoenixEvalJudge classifies against a real model via the 0.29 API."""
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set")

    from eval_harness.judges import PhoenixEvalJudge

    judge = PhoenixEvalJudge(
        model=os.environ.get("PHOENIX_EVAL_MODEL", "gpt-4o-mini"),  # overridable, not hardcoded
        prompt_template="Is the following statement correct? {prompt}\nAnswer CORRECT or INCORRECT.",
        choices={"CORRECT": 1.0, "INCORRECT": 0.0},
        name="phoenix-live-correctness",
    )
    verdict = judge.evaluate("2 + 2 = 4")
    assert 0.0 <= verdict.score <= 1.0
    assert verdict.raw.get("label") in {"CORRECT", "INCORRECT", None}
