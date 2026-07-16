"""BrainTrust live-integration tests (opt-in).

These exercise the pieces that cannot run in the air-gapped suite: the ``braintrust`` dataset
source against a real dataset, and an LLM-based ``autoevals`` scorer against a real provider.
They are marked ``integration`` and self-skip unless the relevant SDK is installed AND the
required credentials/targets are present in the environment — so the offline suite stays green.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.integration


def test_braintrust_dataset_live() -> None:
    pytest.importorskip("braintrust")
    if not os.environ.get("BRAINTRUST_API_KEY"):
        pytest.skip("BRAINTRUST_API_KEY not set")
    project = os.environ.get("BRAINTRUST_TEST_PROJECT")
    dataset = os.environ.get("BRAINTRUST_TEST_DATASET")
    if not (project and dataset):
        pytest.skip("BRAINTRUST_TEST_PROJECT / BRAINTRUST_TEST_DATASET not set")

    from eval_harness.braintrust_client import fetch_dataset_items

    items = fetch_dataset_items(project_name=project, dataset_name=dataset)
    assert isinstance(items, list)
    for it in items:
        assert set(it) == {"id", "inputs", "expected", "metadata"}


def test_autoevals_factuality_live() -> None:
    pytest.importorskip("autoevals")
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set")

    from eval_harness.core.types import EvalItem, RunContext, TargetOutput
    from eval_harness.scorers import AutoevalsScorer

    scorer = AutoevalsScorer(scorer="Factuality")
    res = scorer.score(
        EvalItem(id="1", inputs={"question": "What is 2+2?"}, expected="4"),
        TargetOutput(output="The answer is 4."),
        RunContext(config={}),
    )
    assert res.name == "Factuality"
    assert 0.0 <= res.value <= 1.0
