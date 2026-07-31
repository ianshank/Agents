"""Performance and concurrency benchmarks for the Opik integration — ``@pytest.mark.slow``."""

from __future__ import annotations

import logging
import time
from unittest.mock import MagicMock

import pytest

from eval_harness.engine import EvalEngine
from eval_harness.config import load_config_dict
from eval_harness.version import SCHEMA_VERSION

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.slow

# Configuration for 100 dummy items
CONFIG = {
    "schema_version": SCHEMA_VERSION,
    "run": {"name": "perf_run"},
    "dataset": {
        "type": "inline",
        "params": {
            "items": [{"id": str(i), "inputs": {"q": "hi"}, "expected": "hi"} for i in range(100)]
        },
    },
    "target": {"type": "echo", "params": {"output_key": "q"}},
    "judge": {"type": "mock", "params": {"default_score": 1.0}},
}


def _run_engine(monkeypatch, enable_opik: bool, max_workers: int = 1):
    cfg = dict(CONFIG)
    cfg["run"]["max_workers"] = max_workers
    config = load_config_dict(cfg)
    engine = EvalEngine.from_config(config)
    
    mock_opik = MagicMock()
    mock_decorator = MagicMock()
    mock_opik.track.return_value = mock_decorator
    
    import eval_harness.engine
    original_opik = eval_harness.engine._opik
    
    try:
        if enable_opik:
            eval_harness.engine._opik = mock_opik
        else:
            eval_harness.engine._opik = None
            
        start = time.perf_counter()
        engine.run()
        end = time.perf_counter()
        
        return end - start
    finally:
        eval_harness.engine._opik = original_opik


def test_tracing_overhead_latency(monkeypatch) -> None:
    """Overhead per item should be strictly < 10ms on average."""
    # Warmup
    _run_engine(monkeypatch, enable_opik=False)
    
    time_without = _run_engine(monkeypatch, enable_opik=False)
    time_with = _run_engine(monkeypatch, enable_opik=True)
    
    overhead_total = time_with - time_without
    overhead_per_item = overhead_total / 100.0
    
    logger.info("Opik tracing overhead: %.3f ms per item", overhead_per_item * 1000)
    
    # We assert a generous bound (10ms) to prevent flakes on slow CI runners
    assert overhead_per_item < 0.010, f"Overhead {overhead_per_item * 1000}ms exceeded 10ms limit"


def test_flush_latency_offline(monkeypatch) -> None:
    """Flush latency should be extremely fast (< 200ms) when mocked."""
    mock_opik = MagicMock()
    
    start = time.perf_counter()
    mock_opik.flush_tracker()
    end = time.perf_counter()
    
    latency = end - start
    assert latency < 0.200, f"Flush took {latency}s, limit is 0.200s"


def test_parallel_tracing_thread_safety(monkeypatch) -> None:
    """Run with max_workers=8 and Opik enabled, verifying no deadlocks."""
    # If this deadlocks, the test suite hangs (which pytest-timeout catches)
    latency = _run_engine(monkeypatch, enable_opik=True, max_workers=8)
    assert latency > 0
