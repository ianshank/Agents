"""Unit tests for the Opik observability integration in the EvalEngine."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from eval_harness.engine import EvalEngine
from tests.test_engine import _engine

logger = logging.getLogger(__name__)


def test_engine_run_without_opik(monkeypatch):
    """When _opik is None, the engine runs successfully (graceful degradation)."""
    monkeypatch.setattr("eval_harness.engine._opik", None)
    _config, engine = _engine()
    run = engine.run()
    assert len(run.items) == 2


def test_engine_flush_called():
    """When _opik is present, flush_tracker() is called at the end of the run."""
    mock_opik = MagicMock()
    
    # We must patch the _opik reference in the eval_harness.engine module
    import eval_harness.engine
    original_opik = eval_harness.engine._opik
    
    try:
        eval_harness.engine._opik = mock_opik
        _config, engine = _engine()
        engine.run()
        
        mock_opik.flush_tracker.assert_called_once()
    finally:
        eval_harness.engine._opik = original_opik


def test_engine_track_called_per_item():
    """When opik_client is present, log_item is called for each item."""
    mock_client = MagicMock()
    _config, engine = _engine()
    engine.opik_client = mock_client
    engine.run()
    
    # In test_engine.CONFIG, there are 2 items.
    assert mock_client.log_item.call_count == 2


def test_opik_flush_exception_swallowed():
    """If flush_tracker raises an Exception, it is caught and the run completes."""
    mock_opik = MagicMock()
    mock_opik.flush_tracker.side_effect = Exception("Opik network error")
    
    import eval_harness.engine
    original_opik = eval_harness.engine._opik
    
    try:
        eval_harness.engine._opik = mock_opik
        _config, engine = _engine()
        
        # This should not raise an exception
        run = engine.run()
        assert len(run.items) == 2
    finally:
        eval_harness.engine._opik = original_opik
