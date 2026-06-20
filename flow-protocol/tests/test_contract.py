"""Contract round-trip, immutability, and validation tests for flow_protocol."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from flow_protocol import ConfidenceChannel, FlowResult, OracleResult
from flow_protocol.version import PROTOCOL_VERSION


def test_flow_result_roundtrips_via_json() -> None:
    fr = FlowResult(
        instance_id="i1",
        flow_type="mcts",
        agent_version="abc123",
        domain="sdlc",
        output={"patch": "diff"},
        raw_confidence=0.7,
        confidence_channel=ConfidenceChannel(per_step=(0.4, 0.8), signals={"sc": 0.6}),
        seed=42,
    )
    restored = FlowResult.model_validate_json(fr.model_dump_json())
    assert restored == fr
    assert restored.protocol_version == PROTOCOL_VERSION


def test_oracle_result_roundtrips_and_reports_indeterminate() -> None:
    determinate = OracleResult(
        instance_id="i1", verdict=True, oracle_tier="property", oracle_id="o1"
    )
    indeterminate = OracleResult(instance_id="i2", oracle_tier="property", oracle_id="o1")
    assert OracleResult.model_validate_json(determinate.model_dump_json()) == determinate
    assert determinate.is_indeterminate is False
    assert indeterminate.verdict is None
    assert indeterminate.is_indeterminate is True


def test_raw_confidence_is_optional_for_outcome_only_flows() -> None:
    fr = FlowResult(instance_id="i1", flow_type="noop", agent_version="v0", domain="sdlc")
    assert fr.raw_confidence is None
    assert fr.confidence_channel is None


@pytest.mark.parametrize("bad", [-0.01, 1.01])
def test_raw_confidence_out_of_range_rejected(bad: float) -> None:
    with pytest.raises(ValidationError):
        FlowResult(
            instance_id="i1", flow_type="b", agent_version="v0", domain="sdlc", raw_confidence=bad
        )


def test_models_are_frozen() -> None:
    fr = FlowResult(instance_id="i1", flow_type="b", agent_version="v0", domain="sdlc")
    with pytest.raises(ValidationError):
        fr.raw_confidence = 0.5  # type: ignore[misc]


def test_extra_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        FlowResult(
            instance_id="i1",
            flow_type="b",
            agent_version="v0",
            domain="sdlc",
            bogus="nope",  # type: ignore[call-arg]
        )


def test_oracle_tier_constrained() -> None:
    with pytest.raises(ValidationError):
        OracleResult(instance_id="i1", verdict=True, oracle_tier="psychic", oracle_id="o1")  # type: ignore[arg-type]
