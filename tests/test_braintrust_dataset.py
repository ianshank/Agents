"""BrainTrust dataset source — offline tests.

``fetch_dataset_items`` and the registered ``braintrust`` dataset source are exercised with
no network: the shared ``fake_braintrust`` fixture (``conftest.py``) injects a fake
``braintrust`` whose ``init_dataset`` returns dict records, and the SDK's absence is
simulated with a ``None`` entry so the fail-fast (RuntimeError) path runs for real.
"""

from __future__ import annotations

import sys

import pytest

from eval_harness.braintrust_client import fetch_dataset_items
from eval_harness.core.types import EvalItem
from eval_harness.datasets import BrainTrustDataset
from eval_harness.plugins import DATASETS


def test_fetch_dataset_items_maps_fields(fake_braintrust) -> None:
    records = [
        {"id": "a", "input": {"q": 1}, "expected": "yes", "metadata": {"k": "v"}},
        {"id": "b", "input": {"q": 2}},  # expected / metadata absent (NotRequired)
    ]
    fake_braintrust(init_dataset_records=records)
    items = fetch_dataset_items(project_name="p", dataset_name="d")
    assert items[0] == {"id": "a", "inputs": {"q": 1}, "expected": "yes", "metadata": {"k": "v"}}
    assert items[1] == {"id": "b", "inputs": {"q": 2}, "expected": None, "metadata": {}}


def test_braintrust_dataset_registered_and_loads(fake_braintrust) -> None:
    fake_braintrust(init_dataset_records=[{"id": "1", "input": {"text": "hi"}, "expected": "hi"}])
    ds = DATASETS.create("braintrust", {"project_name": "p", "name": "d"})
    assert isinstance(ds, BrainTrustDataset)
    items = list(ds.load())
    assert len(items) == 1
    assert isinstance(items[0], EvalItem)
    assert items[0].id == "1"
    assert items[0].inputs == {"text": "hi"}
    assert items[0].expected == "hi"


def test_braintrust_dataset_idless_records_get_positional_index(fake_braintrust) -> None:
    # Records without an id must not all collide on the string "None" — each falls back to
    # its positional index (guards the shared _to_item fix).
    fake_braintrust(init_dataset_records=[{"input": {"n": 1}}, {"input": {"n": 2}}])
    items = list(DATASETS.create("braintrust", {"project_name": "p", "name": "d"}).load())
    assert [it.id for it in items] == ["0", "1"]


def test_braintrust_dataset_passes_project_name_version(fake_braintrust) -> None:
    capture: dict = {}
    fake_braintrust(init_dataset_records=[], capture=capture)
    list(DATASETS.create("braintrust", {"project_name": "proj", "name": "ds", "version": "42"}).load())
    assert capture == {"project": "proj", "name": "ds", "version": "42"}


def test_braintrust_dataset_omits_version_when_unset(fake_braintrust) -> None:
    # No version param → "version" is not passed to init_dataset (SDK default = latest).
    capture: dict = {}
    fake_braintrust(init_dataset_records=[], capture=capture)
    list(DATASETS.create("braintrust", {"project_name": "proj", "name": "ds"}).load())
    assert capture == {"project": "proj", "name": "ds"}


def test_braintrust_dataset_raises_without_sdk(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "braintrust", None)  # force ImportError on lazy import
    with pytest.raises(RuntimeError, match="braintrust"):
        fetch_dataset_items(project_name="p", dataset_name="d")
