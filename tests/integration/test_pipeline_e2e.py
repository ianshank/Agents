"""Phase 3 — Full pipeline E2E tests (CLI → Engine → Judge → Sink).

Validates the complete evaluation pipeline from config to results using
real API calls. Tests both programmatic (EvalEngine) and CLI interfaces.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path

import pytest

from eval_harness.config import load_config
from eval_harness.engine import EvalEngine

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
VENV_PYTHON = str(PROJECT_ROOT / ".venv" / "Scripts" / "python")


# ---------------------------------------------------------------------------
# Engine-level E2E
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.slow
class TestEnginePipeline:
    """Validate EvalEngine.from_config() with real judge and sinks."""

    def test_engine_with_mock_judge(self, tmp_path: Path) -> None:
        """Full engine run with mock judge produces valid RunResult (no API needed)."""
        config_path = CONFIG_DIR / "eval.example.yaml"
        if not config_path.exists():
            pytest.skip(f"Config not found: {config_path}")

        from eval_harness.langfuse_client import NullLangfuseClient

        config = load_config(str(config_path))
        engine = EvalEngine.from_config(config, langfuse_client=NullLangfuseClient())
        result = engine.run()

        assert result is not None
        assert result.config_name == config.run.name
        assert len(result.items) > 0
        logger.info("Engine mock run: %d items", len(result.items))

    def test_engine_with_nemotron_judge(self, nvidia_api_key: str, tmp_path: Path) -> None:
        """Full engine run with NVIDIA Nemotron judge produces scored results."""
        config_path = CONFIG_DIR / "e2e_nemotron.yaml"
        if not config_path.exists():
            pytest.skip(f"Config not found: {config_path}")

        # Set env var for config interpolation
        os.environ["NVIDIA_API_KEY"] = nvidia_api_key

        from eval_harness.langfuse_client import NullLangfuseClient

        config = load_config(str(config_path))
        engine = EvalEngine.from_config(config, langfuse_client=NullLangfuseClient())
        result = engine.run()

        assert result is not None
        assert len(result.items) > 0
        for item_result in result.items:
            assert len(item_result.scores) > 0
            for score in item_result.scores:
                assert 0.0 <= score.value <= 1.0, f"Score {score.name}={score.value} out of range"
        logger.info(
            "Nemotron run: %d items, scores=%s",
            len(result.items),
            {r.item.id: [(s.name, s.value) for s in r.scores] for r in result.items},
        )

    def test_engine_json_file_sink(self, tmp_path: Path) -> None:
        """Engine writes valid JSON to file sink."""
        out_file = tmp_path / "results.json"
        config_yaml = f"""\
schema_version: "1.0"
run:
  name: "e2e-json-sink-test"
  seed: 42
dataset:
  type: inline
  params:
    items:
      - id: q1
        inputs: {{ question: "hello" }}
        expected: "hello"
target:
  type: echo
  params:
    output_key: question
scorers:
  - type: exact_match
    params: {{ name: exact }}
judge:
  type: mock
  params:
    default_score: 1.0
sinks:
  - type: json_file
    params: {{ path: "{out_file.as_posix()}" }}
"""
        config_path = tmp_path / "test_config.yaml"
        config_path.write_text(config_yaml, encoding="utf-8")

        from eval_harness.langfuse_client import NullLangfuseClient

        config = load_config(str(config_path))
        engine = EvalEngine.from_config(config, langfuse_client=NullLangfuseClient())
        _result = engine.run()  # side-effect: writes to file sink

        assert out_file.exists(), "JSON output file should be created"
        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert "items" in data or "run_id" in data
        logger.info("JSON sink output: %d bytes", out_file.stat().st_size)


# ---------------------------------------------------------------------------
# CLI-level E2E
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestCLIPipeline:
    """Validate the eval-harness CLI entry point."""

    def test_cli_help(self) -> None:
        """eval-harness --help exits 0."""
        result = subprocess.run(
            [VENV_PYTHON, "-m", "eval_harness.cli", "--help"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
        assert "eval-harness" in result.stdout or "usage" in result.stdout.lower()

    def test_cli_list_plugins(self) -> None:
        """eval-harness list-plugins shows registered components."""
        result = subprocess.run(
            [VENV_PYTHON, "-m", "eval_harness.cli", "list-plugins"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
        assert "mock" in result.stdout.lower() or "echo" in result.stdout.lower()

    def test_cli_run_with_mock_judge(self) -> None:
        """CLI run with example config (mock judge) exits 0."""
        config_path = CONFIG_DIR / "eval.example.yaml"
        if not config_path.exists():
            pytest.skip(f"Config not found: {config_path}")

        result = subprocess.run(
            [VENV_PYTHON, "-m", "eval_harness.cli", "run", "--config", str(config_path), "--offline"],
            capture_output=True, text=True, timeout=60,
        )
        logger.info("CLI stdout: %s", result.stdout[:500])
        if result.stderr:
            logger.debug("CLI stderr: %s", result.stderr[:500])
        assert result.returncode == 0, f"CLI failed: {result.stderr}"

    @pytest.mark.slow
    def test_cli_run_with_nemotron(self, nvidia_api_key: str) -> None:
        """CLI run with nemotron config against real NVIDIA API."""
        config_path = CONFIG_DIR / "e2e_nemotron.yaml"
        if not config_path.exists():
            pytest.skip(f"Config not found: {config_path}")

        env = os.environ.copy()
        env["NVIDIA_API_KEY"] = nvidia_api_key

        # Nemotron 550B inference can take 2-3 min for multi-item datasets
        cli_timeout = int(os.environ.get("E2E_CLI_TIMEOUT_SECONDS", "300"))
        result = subprocess.run(
            [VENV_PYTHON, "-m", "eval_harness.cli", "run", "--config", str(config_path), "--offline"],
            capture_output=True, text=True, timeout=cli_timeout,
            env=env,
        )
        logger.info("Nemotron CLI stdout: %s", result.stdout[:500])
        assert result.returncode == 0, f"CLI nemotron run failed: {result.stderr}"

    def test_cli_missing_config(self) -> None:
        """CLI with non-existent config gives clear error."""
        result = subprocess.run(
            [VENV_PYTHON, "-m", "eval_harness.cli", "run", "--config", "nonexistent.yaml"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode != 0
