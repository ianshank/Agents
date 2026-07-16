"""BrainTrust dataset source — offline tests.

``fetch_dataset_items`` and the registered ``braintrust`` dataset source are exercised with
no network: the ``braintrust`` SDK is injected as a fake ``sys.modules`` entry whose
``init_dataset`` returns dict records, and its absence is simulated with a ``None`` entry so
the fail-fast (RuntimeError) path runs for real.
"""

from __future__ import annotations

import sys
import types

import pytest

from eval_harness.braintrust_client import fetch_dataset_items
from eval_harness.core.types import EvalItem
from eval_harness.datasets import BrainTrustDataset
from eval_harness.plugins import DATASETS


def _install_fake_braintrust(monkeypatch, records, capture: dict | None = None) -> None:
    """Fake ``braintrust`` whose ``init_dataset`` returns an iterable of dict records."""
    mod = types.ModuleType("braintrust")

    def _init_dataset(**kwargs):
        if capture is not None:
            capture.update(kwargs)
        return list(records)  # a Dataset is iterable → a list suffices for the source

    mod.init_dataset = _init_dataset  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "braintrust", mod)


def test_fetch_dataset_items_maps_fields(monkeypatch) -> None:
    records = [
        {"id": "a", "input": {"q": 1}, "expected": "yes", "metadata": {"k": "v"}},
        {"id": "b", "input": {"q": 2}},  # expected / metadata absent (NotRequired)
    ]
    _install_fake_braintrust(monkeypatch, records)
    items = fetch_dataset_items(project_name="p", dataset_name="d")
    assert items[0] == {"id": "a", "inputs": {"q": 1}, "expected": "yes", "metadata": {"k": "v"}}
    assert items[1] == {"id": "b", "inputs": {"q": 2}, "expected": None, "metadata": {}}


def test_braintrust_dataset_registered_and_loads(monkeypatch) -> None:
    _install_fake_braintrust(monkeypatch, [{"id": "1", "input": {"text": "hi"}, "expected": "hi"}])
    ds = DATASETS.create("braintrust", {"project": "p", "name": "d"})
    assert isinstance(ds, BrainTrustDataset)
    items = list(ds.load())
    assert len(items) == 1
    assert isinstance(items[0], EvalItem)
    assert items[0].id == "1"
    assert items[0].inputs == {"text": "hi"}
    assert items[0].expected == "hi"


def test_braintrust_dataset_passes_project_name_version(monkeypatch) -> None:
    capture: dict = {}
    _install_fake_braintrust(monkeypatch, [], capture=capture)
    list(DATASETS.create("braintrust", {"project": "proj", "name": "ds", "version": "42"}).load())
    assert capture == {"project": "proj", "name": "ds", "version": "42"}


def test_braintrust_dataset_raises_without_sdk(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "braintrust", None)  # force ImportError on lazy import
    with pytest.raises(RuntimeError, match="braintrust"):
        fetch_dataset_items(project_name="p", dataset_name="d")
