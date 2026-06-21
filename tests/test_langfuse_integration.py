"""Langfuse integration tests — uses mocks, no network required."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from eval_harness.langfuse_client import (  # type: ignore[import-not-found]
    NullLangfuseClient,
    SDKLangfuseClient,
    langfuse_context,
    observe,
)


@patch("langfuse.Langfuse")
def test_client_initializes_from_env(mock_langfuse_class, monkeypatch):
    """SDKLangfuseClient picks up credentials from environment variables."""
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test-env")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test-env")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://test.example.com")

    SDKLangfuseClient()

    mock_langfuse_class.assert_called_once_with(
        secret_key="sk-test-env",
        public_key="pk-test-env",
        host="https://test.example.com",
    )


@patch("langfuse.Langfuse")
def test_client_kwargs_override_env(mock_langfuse_class, monkeypatch):
    """Explicit kwargs take precedence over env vars."""
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-from-env")
    SDKLangfuseClient(secret_key="sk-explicit")

    call_kwargs = mock_langfuse_class.call_args[1]
    assert call_kwargs["secret_key"] == "sk-explicit"


@patch("langfuse.Langfuse")
def test_client_works_without_env_vars(mock_langfuse_class, monkeypatch):
    """SDKLangfuseClient doesn't crash when env vars are absent."""
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)

    SDKLangfuseClient()
    mock_langfuse_class.assert_called_once_with()


def test_observe_transparent_fallback():
    """observe() acts as a no-op decorator when langfuse is not installed."""

    @observe()
    def dummy_func(x: int) -> int:
        return x + 1

    assert dummy_func(5) == 6


@patch("langfuse.Langfuse")
def test_link_dataset_item(mock_langfuse_class):
    """link_dataset_item calls the correct SDK API."""
    mock_lf_instance = mock_langfuse_class.return_value
    client = SDKLangfuseClient()

    client.link_dataset_item(
        item_id="item-123",
        trace_id="trace-456",
        run_name="my-run",
        run_description="desc",
    )

    mock_lf_instance.api.dataset_run_items.create.assert_called_once_with(
        run_name="my-run",
        run_description="desc",
        dataset_item_id="item-123",
        trace_id="trace-456",
    )


@patch("langfuse.Langfuse")
def test_log_score(mock_langfuse_class):
    """log_score calls create_score on the underlying SDK."""
    mock_lf_instance = mock_langfuse_class.return_value
    client = SDKLangfuseClient()

    client.log_score(
        run_id="run-1",
        item_id="item-1",
        name="accuracy",
        value=0.95,
        comment="good",
    )

    mock_lf_instance.create_score.assert_called_once_with(
        name="accuracy",
        value=0.95,
        comment="good",
        trace_id="item-1",
        metadata={"run_id": "run-1"},
    )


@patch("langfuse.Langfuse")
def test_flush(mock_langfuse_class):
    """flush() delegates to the SDK."""
    mock_lf_instance = mock_langfuse_class.return_value
    client = SDKLangfuseClient()
    client.flush()
    mock_lf_instance.flush.assert_called_once()


@patch("langfuse.Langfuse")
def test_get_dataset_items(mock_langfuse_class):
    """get_dataset_items returns normalized dicts."""
    mock_lf_instance = mock_langfuse_class.return_value
    mock_item = MagicMock()
    mock_item.id = "ds-item-1"
    mock_item.input = {"q": "hello"}
    mock_item.expected_output = "world"
    mock_item.metadata = {"source": "test"}
    mock_lf_instance.get_dataset.return_value.items = [mock_item]

    client = SDKLangfuseClient()
    items = client.get_dataset_items("my-dataset")

    assert len(items) == 1
    assert items[0] == {
        "id": "ds-item-1",
        "inputs": {"q": "hello"},
        "expected": "world",
        "metadata": {"source": "test"},
    }


def test_null_client_records_scores():
    """NullLangfuseClient stores scores in memory."""
    client = NullLangfuseClient()
    client.log_score(run_id="r", item_id="i", name="s", value=0.5)
    assert len(client.scores) == 1
    assert client.scores[0]["name"] == "s"


def test_null_client_flush():
    """NullLangfuseClient.flush() sets flushed flag."""
    client = NullLangfuseClient()
    assert not client.flushed
    client.flush()
    assert client.flushed


def test_langfuse_context_returns_none_without_sdk():
    """SafeLangfuseContext returns None when langfuse is not installed."""
    result = langfuse_context.get_current_trace_id()
    # When langfuse is installed it may return None anyway (no active trace)
    assert result is None or isinstance(result, str)


def test_langfuse_context_with_mocked_decorators():
    from importlib import import_module
    from unittest.mock import MagicMock, patch

    mock_decorators = MagicMock()
    mock_decorators.langfuse_context.get_current_trace_id.return_value = "mocked-trace-id-123"

    def custom_import(name, package=None):
        if name == "langfuse.decorators":
            return mock_decorators
        return import_module(name, package)

    with patch("eval_harness.langfuse_client.import_module", side_effect=custom_import):
        result = langfuse_context.get_current_trace_id()
        assert result == "mocked-trace-id-123"


def test_observe_with_mocked_decorators():
    from unittest.mock import MagicMock, patch

    mock_decorators = MagicMock()
    mock_observe = MagicMock()
    mock_decorators.observe = mock_observe

    def custom_import(name, package=None):
        if name == "langfuse.decorators":
            return mock_decorators
        from importlib import import_module

        return import_module(name, package)

    with patch("eval_harness.langfuse_client.import_module", side_effect=custom_import):
        res = observe("arg1", kwarg="val")
        mock_observe.assert_called_once_with("arg1", kwarg="val")
        assert res is mock_observe.return_value


def test_sdk_client_import_error():
    from unittest.mock import patch

    import pytest

    from eval_harness.langfuse_client import SDKLangfuseClient

    def custom_import(name, package=None):
        if name == "langfuse":
            raise ImportError("mocked import error")
        from importlib import import_module

        return import_module(name, package)

    with (
        patch("eval_harness.langfuse_client.import_module", side_effect=custom_import),
        pytest.raises(RuntimeError, match="The 'langfuse' package is required"),
    ):
        SDKLangfuseClient()


@patch("langfuse.Langfuse")
def test_link_dataset_item_exception(mock_langfuse_class, caplog):
    import logging

    mock_lf_instance = mock_langfuse_class.return_value
    mock_lf_instance.api.dataset_run_items.create.side_effect = RuntimeError("api error")

    client = SDKLangfuseClient()

    with caplog.at_level(logging.ERROR):
        client.link_dataset_item(
            item_id="item-123",
            trace_id="trace-456",
            run_name="my-run",
        )
    assert "Failed to link trace to dataset item" in caplog.text


def test_null_client_link_dataset_item():
    client = NullLangfuseClient()
    # Should be a no-op and not raise any exceptions
    client.link_dataset_item(item_id="1", trace_id="2", run_name="3")
