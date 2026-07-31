"""Unit tests for src/eval_harness/opik_client."""

import pytest
from unittest.mock import MagicMock, patch

from eval_harness.opik_client import (
    OpikClient,
    NullOpikClient,
    SDKOpikClient,
    build_client,
    ENV_OPIK_PROJECT_NAME,
)


def test_null_opik_client_behavior() -> None:
    client = NullOpikClient(dataset_items={"my_ds": [{"id": "1", "inputs": {"q": "hi"}}]})
    assert isinstance(client, OpikClient)

    # Test get_dataset_items
    items = client.get_dataset_items("my_ds")
    assert len(items) == 1
    assert items[0]["id"] == "1"
    assert client.get_dataset_items("missing") == []

    # Test log_score
    client.log_score(run_id="run_1", item_id="item_1", name="accuracy", value=0.95, comment="good")
    assert len(client.scores) == 1
    assert client.scores[0]["name"] == "accuracy"
    assert client.scores[0]["value"] == 0.95

    # Test log_item
    client.log_item(
        run_id="run_1",
        item_id="item_1",
        input={"q": "hi"},
        output={"a": "hello"},
        expected={"a": "hello"},
        scores={"accuracy": 0.95},
        metadata={"k": "v"},
    )
    assert len(client.items) == 1
    assert client.items[0]["item_id"] == "item_1"

    # Test prompt fallback
    assert client.get_prompt("demo_prompt") is None

    # Test flush
    assert not client.flushed
    client.flush()
    assert client.flushed


def test_build_client_disabled() -> None:
    client = build_client(enabled=False)
    assert isinstance(client, NullOpikClient)


def test_build_client_enabled_without_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force opik import error
    with patch.dict("sys.modules", {"opik": None}):
        client = build_client(enabled=True, project_name="test-project")
        assert isinstance(client, NullOpikClient)


def test_sdk_opik_client_mocked() -> None:
    mock_opik_sdk = MagicMock()
    mock_trace = MagicMock()
    mock_opik_sdk.Opik.return_value.trace.return_value = mock_trace

    # Dataset item mock
    mock_dataset_item = MagicMock()
    mock_dataset_item.id = "ds_item_1"
    mock_dataset_item.input = {"q": "hi"}
    mock_dataset_item.expected_output = "hello"
    mock_dataset_item.metadata = {"tag": "v1"}
    
    mock_dataset = MagicMock()
    mock_dataset.items = [mock_dataset_item]
    mock_opik_sdk.Opik.return_value.get_dataset.return_value = mock_dataset

    # Prompt mock
    mock_prompt = MagicMock()
    mock_prompt.prompt = "You are a helpful assistant."
    mock_opik_sdk.Opik.return_value.get_prompt.return_value = mock_prompt

    with patch.dict("sys.modules", {"opik": mock_opik_sdk}):
        client = SDKOpikClient(project_name="my-proj")
        
        # Test log_score
        client.log_score(run_id="r1", item_id="i1", name="exact_match", value=1.0)
        mock_trace.log_feedback_score.assert_called_with(name="exact_match", value=1.0, reason=None)

        # Test log_item
        client.log_item(
            run_id="r1",
            item_id="i1",
            input={"q": "test"},
            output="answer",
            scores={"exact_match": 1.0},
        )
        mock_opik_sdk.Opik.return_value.trace.assert_called()

        # Test get_dataset_items
        items = client.get_dataset_items("test_dataset")
        assert len(items) == 1
        assert items[0]["id"] == "ds_item_1"
        assert items[0]["inputs"] == {"q": "hi"}

        # Test get_prompt
        prompt_text = client.get_prompt("test_prompt")
        assert prompt_text == "You are a helpful assistant."

        # Test flush
        client.flush()
        mock_opik_sdk.Opik.return_value.flush.assert_called_once()


def test_sdk_opik_client_error_handling() -> None:
    mock_opik_sdk = MagicMock()
    mock_opik_sdk.Opik.return_value.trace.side_effect = Exception("Opik trace error")
    mock_opik_sdk.Opik.return_value.get_dataset.side_effect = Exception("Opik dataset error")
    mock_opik_sdk.Opik.return_value.get_prompt.side_effect = Exception("Opik prompt error")
    mock_opik_sdk.Opik.return_value.flush.side_effect = Exception("Opik flush error")

    with patch.dict("sys.modules", {"opik": mock_opik_sdk}):
        client = SDKOpikClient(project_name="my-proj")
        # Ensure errors are caught and logged without raising exceptions
        client.log_score(run_id="r1", item_id="i1", name="exact_match", value=1.0)
        client.log_item(run_id="r1", item_id="i1", input="in", output="out")
        assert client.get_dataset_items("err") == []
        assert client.get_prompt("err") is None
        client.flush()

