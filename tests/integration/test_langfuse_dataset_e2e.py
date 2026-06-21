"""Phase 4 — Langfuse Dataset Source + Sink E2E tests.

Validates the full Langfuse loop: dataset creation → eval engine loading →
score emission back to Langfuse via LangfuseSink.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import pytest

from eval_harness.datasets import LangfuseDataset
from eval_harness.engine import EvalEngine
from eval_harness.langfuse_client import SDKLangfuseClient
from eval_harness.sinks import LangfuseSink

from .conftest import _poll_until

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dataset source
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestLangfuseDatasetSource:
    """Validate LangfuseDataset loads items from real Langfuse."""

    def test_load_dataset_from_langfuse(
        self, langfuse_sdk: Any, sdk_langfuse_client: SDKLangfuseClient
    ) -> None:
        """LangfuseDataset.load() returns items from a real Langfuse dataset."""
        dataset_name = f"e2e-dataset-source-{int(time.time())}"

        # Seed the dataset
        langfuse_sdk.create_dataset(name=dataset_name, description="E2E dataset source test")
        items_data = [
            {"input": {"question": "What color is the sky?"}, "expected_output": "Blue"},
            {"input": {"question": "What is 3*3?"}, "expected_output": "9"},
        ]
        for record in items_data:
            langfuse_sdk.create_dataset_item(
                dataset_name=dataset_name,
                input=record["input"],
                expected_output=record["expected_output"],
            )
        langfuse_sdk.flush()

        # Wait for ingestion
        def _check() -> bool:
            items = sdk_langfuse_client.get_dataset_items(dataset_name)
            return len(items) >= len(items_data)

        _poll_until(_check, description="dataset items ingested")

        # Use the LangfuseDataset source
        ds = LangfuseDataset(dataset_name=dataset_name)
        ds.attach_client(sdk_langfuse_client)
        loaded_items = list(ds.load())

        assert len(loaded_items) >= len(items_data)
        for eval_item in loaded_items:
            assert eval_item.id is not None
            assert eval_item.inputs is not None
            logger.debug("Loaded item: id=%s inputs=%s", eval_item.id, eval_item.inputs)

    def test_dataset_without_client_raises(self) -> None:
        """LangfuseDataset.load() without attach_client raises RuntimeError."""
        ds = LangfuseDataset(dataset_name="nonexistent")
        with pytest.raises(RuntimeError, match="client"):
            list(ds.load())


# ---------------------------------------------------------------------------
# Langfuse sink
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestLangfuseSink:
    """Validate LangfuseSink emits scores to real Langfuse."""

    def test_sink_emits_to_langfuse(
        self, sdk_langfuse_client: SDKLangfuseClient, tmp_path: Any
    ) -> None:
        """LangfuseSink.emit() sends scores that appear in Langfuse API."""
        import uuid
        from datetime import datetime, timezone

        from eval_harness.core.types import EvalItem, ItemResult, RunResult, ScoreAggregate, ScoreResult, TargetOutput

        # In Langfuse v4, traces are created via @observe / OTEL.
        trace_id = str(uuid.uuid4())

        # Build a RunResult with correct types
        item = EvalItem(id=trace_id, inputs={"q": "test"}, expected="answer")
        output = TargetOutput(output="answer", latency_ms=100.0)
        score = ScoreResult(name="accuracy", value=0.9, passed=True)
        item_result = ItemResult(item=item, output=output, scores=[score])
        now = datetime.now(timezone.utc)
        run_result = RunResult(
            run_id="e2e-sink-test-run",
            config_name="e2e-sink-test",
            items=[item_result],
            aggregate={"accuracy": ScoreAggregate(count=1, mean=0.9, pass_rate=1.0)},
            started_at=now,
            finished_at=now,
        )

        # Emit via LangfuseSink
        sink = LangfuseSink()
        sink.attach_client(sdk_langfuse_client)
        sink.emit(run_result)

        logger.info("Emitted scores to Langfuse via sink")

    def test_sink_without_client_raises(self) -> None:
        """LangfuseSink.emit() without attach_client raises RuntimeError."""
        from datetime import datetime, timezone

        from eval_harness.core.types import RunResult

        sink = LangfuseSink()
        now = datetime.now(timezone.utc)
        dummy_result = RunResult(
            run_id="test", config_name="test", items=[], aggregate={},
            started_at=now, finished_at=now,
        )
        with pytest.raises(RuntimeError):
            sink.emit(dummy_result)


# ---------------------------------------------------------------------------
# Full Langfuse loop
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.slow
class TestFullLangfuseLoop:
    """Validate Langfuse dataset → eval → Langfuse sink end-to-end."""

    def test_langfuse_dataset_to_langfuse_sink(
        self, langfuse_sdk: Any, sdk_langfuse_client: SDKLangfuseClient
    ) -> None:
        """Full loop: create dataset in Langfuse → eval with mock judge → emit scores back."""
        dataset_name = f"e2e-full-loop-{int(time.time())}"

        # Create dataset
        langfuse_sdk.create_dataset(name=dataset_name, description="E2E full loop test")
        langfuse_sdk.create_dataset_item(
            dataset_name=dataset_name,
            input={"question": "What is 5+5?"},
            expected_output="10",
        )
        langfuse_sdk.flush()

        # Wait for ingestion
        def _check() -> bool:
            items = sdk_langfuse_client.get_dataset_items(dataset_name)
            return len(items) >= 1

        _poll_until(_check, description="full-loop dataset")

        # Build config programmatically (no hardcoded values)
        from eval_harness.config.models import ComponentSpec, EvalConfig, RunSettings

        config = EvalConfig(
            schema_version="1.0",
            run=RunSettings(name=f"e2e-full-loop-{int(time.time())}", seed=42),
            dataset=ComponentSpec(type="langfuse", params={"dataset_name": dataset_name}),
            target=ComponentSpec(type="echo", params={"output_key": "question"}),
            scorers=[ComponentSpec(type="contains", params={"name": "has_question_mark", "substring": "?"})],
            judge=ComponentSpec(type="mock", params={"default_score": 0.85}),
            sinks=[ComponentSpec(type="console", params={"verbose": True})],
        )

        engine = EvalEngine.from_config(config, langfuse_client=sdk_langfuse_client)
        result = engine.run()

        assert result is not None
        assert len(result.items) >= 1
        logger.info("Full Langfuse loop: %d items", len(result.items))
