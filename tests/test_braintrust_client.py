"""BrainTrust experiment-export client — offline tests.

``NullBrainTrustClient`` and the ``build_client`` factory are exercised end-to-end with
no network. The SDK client (which logs each item to a BrainTrust experiment via
``experiment.log``) is tested against an injected fake experiment — never the real
``braintrust`` package, which is not installed in the air-gapped suite. The SDK's
absence is simulated with ``sys.modules`` injection so the ImportError fallback runs for
real.
"""

from __future__ import annotations

import logging
import sys
import types

from eval_harness.braintrust_client import (
    NullBrainTrustClient,
    SDKBrainTrustClient,
    build_client,
)


class _RecordingExperiment:
    def __init__(self) -> None:
        self.logged: list[dict] = []
        self.flushed = False

    def log(self, **kwargs) -> None:
        self.logged.append(kwargs)

    def flush(self) -> None:
        self.flushed = True


def _install_fake_braintrust(monkeypatch, experiment, *, init_raises: bool = False) -> None:
    """Make ``import braintrust`` resolve to a fake whose ``init`` returns ``experiment``."""
    mod = types.ModuleType("braintrust")

    def _init(**_kwargs):
        if init_raises:
            raise RuntimeError("braintrust down")
        return experiment

    mod.init = _init  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "braintrust", mod)


# -- Null client -------------------------------------------------------------


def test_null_client_records_and_flushes() -> None:
    c = NullBrainTrustClient()
    c.log_item(run_id="r", item_id="i", input={"q": 1}, output="a", expected="b", scores={"acc": 0.9})
    c.flush()
    assert c.items == [
        {
            "run_id": "r",
            "item_id": "i",
            "input": {"q": 1},
            "output": "a",
            "expected": "b",
            "scores": {"acc": 0.9},
            "metadata": None,
        }
    ]
    assert c.flushed is True


# -- build_client factory ----------------------------------------------------


def test_build_client_returns_null_when_disabled() -> None:
    client = build_client(enabled=False, project_name="p", experiment_name="run-1")
    assert isinstance(client, NullBrainTrustClient)


def test_build_client_falls_back_to_null_without_sdk(monkeypatch, caplog) -> None:
    # A None entry forces the lazy ``import braintrust`` to ImportError (hermetic even if
    # the braintrust extra is installed).
    monkeypatch.setitem(sys.modules, "braintrust", None)
    with caplog.at_level(logging.WARNING):
        client = build_client(enabled=True, project_name="p", experiment_name="run-1")
    assert isinstance(client, NullBrainTrustClient)
    assert any("braintrust" in r.message.lower() for r in caplog.records)


def test_build_client_returns_sdk_when_backend_present(monkeypatch) -> None:
    _install_fake_braintrust(monkeypatch, _RecordingExperiment())
    client = build_client(enabled=True, project_name="p", experiment_name="run-1")
    assert isinstance(client, SDKBrainTrustClient)


def test_build_client_falls_back_to_null_when_init_raises(monkeypatch, caplog) -> None:
    _install_fake_braintrust(monkeypatch, _RecordingExperiment(), init_raises=True)
    with caplog.at_level(logging.DEBUG):
        client = build_client(enabled=True, project_name="p", experiment_name="run-1")
    assert isinstance(client, NullBrainTrustClient)  # init failure → no-op, run continues
    assert caplog.records
    # A failed init (SDK present) must log an error, NOT the "install the SDK" warning.
    assert not any(r.levelno == logging.WARNING for r in caplog.records)


# -- SDK client logs to the experiment ---------------------------------------


def test_sdk_client_logs_item_to_experiment() -> None:
    exp = _RecordingExperiment()
    client = SDKBrainTrustClient(exp)
    client.log_item(
        run_id="r",
        item_id="i",
        input={"q": "x"},
        output="out",
        expected="exp",
        scores={"acc": 0.9},
        metadata={"config_name": "cfg"},
    )
    client.flush()
    assert exp.flushed is True
    assert len(exp.logged) == 1
    row = exp.logged[0]
    assert row["id"] == "i"
    assert row["input"] == {"q": "x"}
    assert row["output"] == "out"
    assert row["expected"] == "exp"
    assert row["scores"] == {"acc": 0.9}
    # run_id is folded into metadata alongside caller-supplied keys.
    assert row["metadata"] == {"config_name": "cfg", "run_id": "r"}


def test_sdk_client_log_item_is_failsafe(caplog) -> None:
    class _BoomExperiment:
        def log(self, **kwargs):
            raise RuntimeError("network down")

    client = SDKBrainTrustClient(_BoomExperiment())
    with caplog.at_level(logging.ERROR):
        client.log_item(run_id="r", item_id="i", input={}, output="o", scores={"acc": 1.0})  # must not raise
    assert caplog.records


def test_sdk_client_flush_is_failsafe(caplog) -> None:
    class _BoomFlush:
        def flush(self):
            raise RuntimeError("flush down")

    client = SDKBrainTrustClient(_BoomFlush())
    with caplog.at_level(logging.ERROR):
        client.flush()  # must not raise
    assert caplog.records
