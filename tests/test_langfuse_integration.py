import os
import unittest
from unittest.mock import MagicMock, patch
import pytest

from eval_harness.langfuse_client import SDKLangfuseClient, NullLangfuseClient, observe, langfuse_context
from eval_harness.judges import OpenAIJudge
from eval_harness.engine import EvalEngine
from eval_harness.config.models import EvalConfig

class TestLangfuseIntegration(unittest.TestCase):
    def setUp(self):
        # Backup environment
        self._old_env = dict(os.environ)

    def tearDown(self):
        # Restore environment
        os.environ.clear()
        os.environ.update(self._old_env)

    @patch("langfuse.Langfuse")
    def test_client_defaults_initialization(self, mock_langfuse_class):
        # Remove env variables if any
        os.environ.pop("LANGFUSE_SECRET_KEY", None)
        os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
        os.environ.pop("LANGFUSE_BASE_URL", None)

        client = SDKLangfuseClient()
        
        # Verify defaults are injected in env
        self.assertEqual(os.environ["LANGFUSE_SECRET_KEY"], "sk-lf-e220d788-d2e0-4e82-bbde-6d1a57ba149f")
        self.assertEqual(os.environ["LANGFUSE_PUBLIC_KEY"], "pk-lf-ad617cfc-ce1b-4c23-8c76-7868605ee6f1")
        self.assertEqual(os.environ["LANGFUSE_BASE_URL"], "https://us.cloud.langfuse.com")

        # Verify client was created with these options
        mock_langfuse_class.assert_called_once_with(
            secret_key="sk-lf-e220d788-d2e0-4e82-bbde-6d1a57ba149f",
            public_key="pk-lf-ad617cfc-ce1b-4c23-8c76-7868605ee6f1",
            host="https://us.cloud.langfuse.com"
        )

    def test_observe_transparent_fallback(self):
        # Verify observe works as a normal decorator when no langfuse available
        with patch("importlib.import_module", side_effect=ImportError):
            @observe()
            def dummy_func(x):
                return x + 1
            
            self.assertEqual(dummy_func(5), 6)

    @patch("langfuse.Langfuse")
    def test_link_dataset_item(self, mock_langfuse_class):
        mock_lf_instance = mock_langfuse_class.return_value
        client = SDKLangfuseClient()
        
        client.link_dataset_item(
            item_id="item-123",
            trace_id="trace-456",
            run_name="my-run",
            run_description="desc"
        )
        
        # Verify api call was made correctly
        mock_lf_instance.api.dataset_run_items.create.assert_called_once_with(
            run_name="my-run",
            run_description="desc",
            dataset_item_id="item-123",
            trace_id="trace-456"
        )

    @patch("langfuse.Langfuse")
    @patch("langfuse.openai.OpenAI")
    def test_openai_judge_attachment(self, mock_lf_openai_class, mock_langfuse_class):
        judge = OpenAIJudge(
            model="gpt-4",
            base_url="https://api.openai.com/v1",
            api_key="test-key"
        )
        
        # Verify initial client is standard OpenAI
        from openai import OpenAI as StandardOpenAI
        self.assertIsInstance(judge.client, StandardOpenAI)
        
        # Attach client
        client = SDKLangfuseClient()
        judge.attach_client(client)
        
        # Verify it swapped to the traced client
        mock_lf_openai_class.assert_called_once_with(
            base_url="https://api.openai.com/v1/",
            api_key="test-key"
        )
        self.assertEqual(judge.client, mock_lf_openai_class.return_value)
