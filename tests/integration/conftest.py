"""Shared fixtures for integration tests.

All integration tests require real API credentials set via environment variables.
Tests are automatically skipped when credentials are absent.
"""

from __future__ import annotations

# Inject system certificate store before any SSL connections are made.
# Fixes CERTIFICATE_VERIFY_FAILED on Windows with corporate proxies.
try:
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    pass  # truststore not installed — rely on default cert bundle

import logging
import os
import time
from typing import Any

import pytest

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Env-var helpers — never hardcode credentials
# ---------------------------------------------------------------------------
_LANGFUSE_ENV_VARS = ("LANGFUSE_SECRET_KEY", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_BASE_URL")
_NVIDIA_ENV_VAR = "NVIDIA_API_KEY"
_OPENAI_ENV_VAR = "OPENAI_API_KEY"

# Integration test constants — overridable via env vars
E2E_DATASET_NAME = os.environ.get("E2E_DATASET_NAME", "eval-harness-e2e-test")
E2E_RUN_NAME_PREFIX = os.environ.get("E2E_RUN_NAME_PREFIX", "e2e-test")
E2E_POLL_INTERVAL_SECONDS = float(os.environ.get("E2E_POLL_INTERVAL_SECONDS", "3"))
E2E_POLL_MAX_RETRIES = int(os.environ.get("E2E_POLL_MAX_RETRIES", "10"))


def _require_env(var: str) -> str:
    """Return the value of an env var or skip the test if unset."""
    val = os.environ.get(var)
    if not val:
        pytest.skip(f"{var} not set — skipping integration test")
    return val


def _poll_until(
    predicate: Any,
    *,
    interval: float = E2E_POLL_INTERVAL_SECONDS,
    max_retries: int = E2E_POLL_MAX_RETRIES,
    description: str = "condition",
) -> Any:
    """Poll a predicate until it returns a truthy value or timeout."""
    for attempt in range(max_retries):
        result = predicate()
        if result:
            logger.debug("Poll succeeded for '%s' on attempt %d", description, attempt + 1)
            return result
        logger.debug("Poll attempt %d/%d for '%s' — retrying in %.1fs", attempt + 1, max_retries, description, interval)
        time.sleep(interval)
    pytest.fail(f"Timed out waiting for '{description}' after {max_retries} attempts")


# ---------------------------------------------------------------------------
# Credential fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def langfuse_credentials() -> dict[str, str]:
    """Require and return Langfuse credentials from env vars."""
    return {
        "secret_key": _require_env("LANGFUSE_SECRET_KEY"),
        "public_key": _require_env("LANGFUSE_PUBLIC_KEY"),
        "host": _require_env("LANGFUSE_BASE_URL"),
    }


@pytest.fixture
def nvidia_api_key() -> str:
    """Require and return the NVIDIA API key from env vars."""
    return _require_env(_NVIDIA_ENV_VAR)


@pytest.fixture
def openai_api_key() -> str:
    """Require and return the OpenAI API key from env vars."""
    return _require_env(_OPENAI_ENV_VAR)


# ---------------------------------------------------------------------------
# Langfuse SDK fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def langfuse_sdk(langfuse_credentials: dict[str, str]) -> Any:
    """Create and yield a real Langfuse SDK client. Flushes on teardown."""
    from langfuse import Langfuse

    lf = Langfuse(
        secret_key=langfuse_credentials["secret_key"],
        public_key=langfuse_credentials["public_key"],
        host=langfuse_credentials["host"],
    )
    yield lf
    lf.flush()


@pytest.fixture
def sdk_langfuse_client(langfuse_credentials: dict[str, str]) -> Any:
    """Create and yield a real SDKLangfuseClient from the eval harness."""
    from eval_harness.langfuse_client import SDKLangfuseClient

    client = SDKLangfuseClient(**langfuse_credentials)
    yield client
    client.flush()


# ---------------------------------------------------------------------------
# Unique test run identifiers
# ---------------------------------------------------------------------------
@pytest.fixture
def unique_run_name() -> str:
    """Generate a unique run name to prevent test cross-contamination."""
    return f"{E2E_RUN_NAME_PREFIX}-{int(time.time())}"
