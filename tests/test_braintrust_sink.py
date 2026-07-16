"""BrainTrust result sink — offline tests.

``BrainTrustSink`` is exercised through the dynamic registry (zero engine wiring). With
``enabled`` defaulting to ``False`` the sink builds a ``NullBrainTrustClient`` at emit time,
so the per-item logging + score-folding logic runs fully offline. The SDK path is covered
against the shared fake ``braintrust`` experiment (``fake_braintrust`` / ``recording_experiment``
from ``conftest.py``) — never the real package.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from eval_harness.braintrust_client import NullBrainTrustClient, SDKBrainTrustClient
from eval_harness.core.types import RunResult
from eval_harness.plugins import SINKS
from eval_harness.sinks import BrainTrustSink


def _run(*items: tuple[str, dict, object, object, list[tuple[str, float]]]) -> RunResult:
    """A RunResult-shaped stand-in (the sink only reads these attributes)."""
    stand_in = SimpleNamespace(
        run_id="run-1",
        config_name="cfg",
        items=[
            SimpleNamespace(
                item=SimpleNamespace(id=iid, inputs=inputs, expected=expected),
                output=SimpleNamespace(output=out),
                scores=[SimpleNamespace(name=n, value=v) for (n, v) in scores],
            )
            for (iid, inputs, out, expected, scores) in items
        ],
    )
    return cast(RunResult, stand_in)


def _braintrust_sink(params: dict[str, object]) -> BrainTrustSink:
    sink = SINKS.create("braintrust", params)
    assert isinstance(sink, BrainTrustSink)
    return sink


def _null_client(sink: BrainTrustSink) -> NullBrainTrustClient:
    client = sink._client
    assert isinstance(client, NullBrainTrustClient)
    return client


# -- offline (Null client) ---------------------------------------------------


def test_braintrust_sink_registered_and_logs_items_offline() -> None:
    sink = _braintrust_sink({})  # enabled defaults False → Null client, no network
    sink.emit(_run(("i1", {"q": "a"}, "out-a", "exp-a", [("acc", 0.9), ("f1", 0.5)])))
    items = _null_client(sink).items
    assert len(items) == 1
    assert items[0]["item_id"] == "i1"
    assert items[0]["input"] == {"q": "a"}
    assert items[0]["output"] == "out-a"
    assert items[0]["expected"] == "exp-a"
    assert items[0]["scores"] == {"acc": 0.9, "f1": 0.5}
    assert items[0]["metadata"] == {"config_name": "cfg"}
    assert _null_client(sink).flushed is True


def test_braintrust_sink_respects_min_value_to_log() -> None:
    sink = _braintrust_sink({"min_value_to_log": 0.6})
    sink.emit(_run(("i1", {}, "out", None, [("acc", 0.9), ("low", 0.3)])))
    items = _null_client(sink).items
    assert len(items) == 1  # the item is still logged (input/output preserved)
    assert items[0]["scores"] == {"acc": 0.9}  # 0.3 filtered from the scores dict


def test_braintrust_sink_min_value_is_inclusive() -> None:
    # A score exactly at the threshold is kept (the filter is >=, not >).
    sink = _braintrust_sink({"min_value_to_log": 0.6})
    sink.emit(_run(("i1", {}, "o", None, [("edge", 0.6), ("below", 0.59)])))
    assert _null_client(sink).items[0]["scores"] == {"edge": 0.6}


def test_braintrust_sink_logs_scoreless_item() -> None:
    # An item with no scores is still logged (input/output preserved) with an empty scores dict.
    sink = _braintrust_sink({})
    sink.emit(_run(("i1", {"q": 1}, "o", None, [])))
    items = _null_client(sink).items
    assert len(items) == 1
    assert items[0]["scores"] == {}
    assert items[0]["input"] == {"q": 1}


def test_braintrust_sink_logs_every_item() -> None:
    sink = _braintrust_sink({})
    sink.emit(
        _run(
            ("i1", {}, "o1", None, [("acc", 1.0)]),
            ("i2", {}, "o2", None, [("acc", 0.0)]),
        )
    )
    assert [i["item_id"] for i in _null_client(sink).items] == ["i1", "i2"]


# -- SDK path (fake experiment) ----------------------------------------------


def test_braintrust_sink_uses_sdk_experiment_when_enabled(fake_braintrust, recording_experiment) -> None:
    capture: dict = {}
    fake_braintrust(experiment=recording_experiment, capture=capture)
    sink = _braintrust_sink({"enabled": True, "project_name": "proj"})
    sink.emit(_run(("i1", {"q": 1}, "out", "exp", [("acc", 0.8)])))
    assert isinstance(sink._client, SDKBrainTrustClient)
    # The experiment is created in the configured project and named after the run id.
    assert capture == {"project": "proj", "experiment": "run-1"}
    assert recording_experiment.flushed is True
    assert len(recording_experiment.logged) == 1
    assert recording_experiment.logged[0]["id"] == "i1"
    assert recording_experiment.logged[0]["scores"] == {"acc": 0.8}
    assert recording_experiment.logged[0]["metadata"] == {"config_name": "cfg", "run_id": "run-1"}
