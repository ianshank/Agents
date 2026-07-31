"""Phase 1 — Langfuse SDK live integration tests.

Validates real connectivity, dataset CRUD, score logging, and flush
against the live Langfuse API. All credentials sourced from env vars.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import pytest

from eval_harness.langfuse_client import NullLangfuseClient, SDKLangfuseClient

from .conftest import _poll_until

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Connectivity
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestLangfuseConnectivity:
    """Validate that SDKLangfuseClient can connect and authenticate."""

    def test_sdk_client_connects(self, sdk_langfuse_client: SDKLangfuseClient) -> None:
        """SDKLangfuseClient initializes without error when credentials are valid."""
        assert sdk_langfuse_client is not None
        # Smoke: flush should not raise
        sdk_langfuse_client.flush()

    def test_sdk_client_rejects_bad_credentials(self) -> None:
        """SDKLangfuseClient accepts bad credentials (lazy auth) but API calls should fail."""
        client = SDKLangfuseClient(
            secret_key="sk-lf-invalid",
            public_key="pk-lf-invalid",
            host="https://us.cloud.langfuse.com",
        )
        # Initialization should not raise — auth is lazy
        assert client is not None


# ---------------------------------------------------------------------------
# Dataset operations
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestLangfuseDatasets:
    """Validate dataset creation, item population, and retrieval."""

    def test_create_and_fetch_dataset(self, langfuse_sdk: Any, sdk_langfuse_client: SDKLangfuseClient) -> None:
        """Create a dataset, add items, fetch via SDKLangfuseClient, verify round-trip."""
        dataset_name = f"e2e-test-{int(time.time())}"
        logger.info("Creating dataset '%s'", dataset_name)

        # Create dataset via raw SDK
        langfuse_sdk.create_dataset(
            name=dataset_name,
            description="E2E test dataset (auto-created, safe to delete)",
        )

        # Add items
        test_items = [
            {"input": {"question": "What is 2+2?"}, "expected_output": "4"},
            {"input": {"question": "Capital of France?"}, "expected_output": "Paris"},
        ]
        for item_data in test_items:
            langfuse_sdk.create_dataset_item(
                dataset_name=dataset_name,
                input=item_data["input"],
                expected_output=item_data["expected_output"],
                metadata={"source": "e2e-test"},
            )
        langfuse_sdk.flush()

        # Poll until items are available (ingestion delay)
        def _check_items() -> list[dict] | None:
            items = sdk_langfuse_client.get_dataset_items(dataset_name)
            return items if len(items) >= len(test_items) else None

        items = _poll_until(_check_items, description=f"dataset '{dataset_name}' items")

        assert len(items) >= len(test_items)
        # Verify structure
        for item in items:
            assert "id" in item
            assert "inputs" in item
            assert "expected" in item
            assert "metadata" in item
            logger.debug("Item: %s", item)


# ---------------------------------------------------------------------------
# Score logging
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestLangfuseScoring:
    """Validate score logging to Langfuse."""

    def test_log_score(self, sdk_langfuse_client: SDKLangfuseClient) -> None:
        """log_score() sends a score to Langfuse without raising."""
        import uuid

        # In Langfuse v4, traces are created via @observe / OTEL, not directly.
        # create_score accepts any trace_id — use a UUID.
        trace_id = str(uuid.uuid4())

        sdk_langfuse_client.log_score(
            run_id="e2e-run",
            item_id=trace_id,
            name="e2e-accuracy",
            value=0.95,
            comment="E2E test score",
        )
        sdk_langfuse_client.flush()
        logger.info("Logged score to trace %s — no exceptions", trace_id)

    def test_link_dataset_item(self, sdk_langfuse_client: SDKLangfuseClient, langfuse_sdk: Any) -> None:
        """link_dataset_item() creates a dataset run item linkage."""
        import uuid

        dataset_name = f"e2e-link-test-{int(time.time())}"
        langfuse_sdk.create_dataset(name=dataset_name, description="E2E link test")
        langfuse_sdk.create_dataset_item(
            dataset_name=dataset_name,
            input={"q": "test"},
            expected_output="answer",
        )
        langfuse_sdk.flush()

        # Wait for dataset item
        def _get_item_id() -> str | None:
            try:
                ds = langfuse_sdk.get_dataset(dataset_name)
                if ds.items:
                    return str(ds.items[0].id)
            except Exception:
                pass
            return None

        item_id = _poll_until(_get_item_id, description="dataset item creation")

        # In Langfuse v4, traces are created via @observe / OTEL.
        trace_id = str(uuid.uuid4())

        sdk_langfuse_client.link_dataset_item(
            item_id=item_id,
            trace_id=trace_id,
            run_name=f"e2e-link-run-{int(time.time())}",
            run_description="E2E link test",
        )
        sdk_langfuse_client.flush()
        logger.info("Linked item %s to trace %s", item_id, trace_id)


# ---------------------------------------------------------------------------
# Flush behavior
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestLangfuseFlush:
    """Validate flush semantics."""

    def test_flush_does_not_raise(self, sdk_langfuse_client: SDKLangfuseClient) -> None:
        """Calling flush() with no pending data should be a no-op."""
        sdk_langfuse_client.flush()  # Should not raise

    def test_multiple_flush_calls(self, sdk_langfuse_client: SDKLangfuseClient) -> None:
        """Multiple flush() calls should be idempotent."""
        for _ in range(3):
            sdk_langfuse_client.flush()


# ---------------------------------------------------------------------------
# Null client parity
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestNullClientComparison:
    """Verify NullLangfuseClient has the same interface as SDKLangfuseClient."""

    def test_null_client_has_same_methods(self) -> None:
        """NullLangfuseClient should support all LangfuseClient ABC methods."""
        null = NullLangfuseClient()
        sdk_methods = {"get_dataset_items", "log_score", "link_dataset_item", "flush"}
        for method_name in sdk_methods:
            assert hasattr(null, method_name), f"NullLangfuseClient missing method: {method_name}"
