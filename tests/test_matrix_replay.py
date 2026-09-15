"""Matrix row for the registered ``replay`` target (floor M1, M2, M3, M6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from eval_harness.core.types import EvalItem, TargetOutput
from eval_harness.plugins import TARGETS
from eval_harness.replay.envelope import ReplayError
from eval_harness.replay.target import ReplayTarget
from tests.test_replay import _envelope


class TestReplayTarget:
    MATRIX_KIND = "target"
    MATRIX_COMPONENTS = ("replay",)

    def test_m1_correctness_exact_replay_reemits_recorded_trajectory(self) -> None:
        env = _envelope()
        target = TARGETS.create("replay", {"envelopes": [env], "mode": "exact"})
        out = target.run(EvalItem(id="i1", inputs={}))
        assert isinstance(out, TargetOutput)
        assert out.trajectory == env.trajectory
        assert out.output == env.output

    def test_m2_edge_missing_envelope_is_a_scored_error(self) -> None:
        target = TARGETS.create("replay", {"envelopes": [], "mode": "exact"})
        out = target.run(EvalItem(id="missing", inputs={}))
        assert out.error is not None
        assert out.trajectory is None

    def test_m3_type_safety_invalid_mode_is_config_error(self) -> None:
        with pytest.raises(ReplayError, match="invalid replay mode"):
            TARGETS.create("replay", {"mode": "live-shadow"})

    def test_m6_error_corrupt_jsonl_fails_closed(self, tmp_path: Path) -> None:
        archive = tmp_path / "bad.jsonl"
        archive.write_text("{this is not json\n", encoding="utf-8")
        target = ReplayTarget(archive=str(archive), mode="exact")
        out = target.run(EvalItem(id="i1", inputs={}))
        assert out.error is not None
        assert "corrupt JSONL" in out.error
