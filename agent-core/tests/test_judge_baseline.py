"""Judge baseline: may_gate + human corpus + kappa/n floors."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_core.config import ConfigError
from agent_core.corpus_provenance import CorpusProvenanceConfig
from agent_core.golden import GoldenItem, GoldenSet
from agent_core.judge_baseline import (
    JudgeBaselineConfig,
    evaluate_against_baseline,
    main,
)
from agent_core.judge_calibration import (
    OrderProbeResult,
    SelfPreferenceResult,
    VerbosityProbeResult,
)
from agent_core.judge_calibration_report import (
    REPORT_SCHEMA_VERSION,
    JudgeCalibrationReport,
    dump_judge_calibration_report,
)
from agent_core.labeling_protocol import LabelingProtocolConfig


def _passing_order() -> OrderProbeResult:
    return OrderProbeResult(n=10, flips=0, flip_rate=0.0, ci_low=0.0, ci_high=0.1, passes=True)


def _passing_verbosity() -> VerbosityProbeResult:
    return VerbosityProbeResult(
        n=10,
        ties=0,
        concise_wins=5,
        expanded_wins=5,
        expanded_win_rate=0.5,
        preference_delta=0.0,
        ci_low=0.2,
        ci_high=0.8,
        passes=True,
    )


def _passing_self_preference() -> SelfPreferenceResult:
    return SelfPreferenceResult(
        judge_family="gpt",
        same_family_n=10,
        same_family_win_rate=0.5,
        same_family_ci_low=0.2,
        same_family_ci_high=0.8,
        other_family_n=10,
        other_family_win_rate=0.5,
        other_family_ci_low=0.2,
        other_family_ci_high=0.8,
        delta=0.0,
        passes=True,
    )


def _report(**overrides: Any) -> JudgeCalibrationReport:
    defaults: dict[str, Any] = dict(
        judge_id="j1",
        artifact_id="art-1",
        n_total=100,
        n_codeterminate=90,
        percent_agreement=0.9,
        kappa=0.85,
        directional_only=False,
        agreement_may_gate=True,
        order_flip=_passing_order(),
        verbosity=_passing_verbosity(),
        self_preference=_passing_self_preference(),
        canary_pass_rate=1.0,
    )
    defaults.update(overrides)
    return JudgeCalibrationReport(schema_version=REPORT_SCHEMA_VERSION, **defaults)


def _human_corpus(n: int) -> GoldenSet:
    items = [
        GoldenItem(item_id=f"i{i}", text=f"t{i}", label=i % 2, meta={"provenance": "human"})
        for i in range(n)
    ]
    return GoldenSet(tuple(items))


def test_baseline_defaults_track_labeling_protocol() -> None:
    cfg = JudgeBaselineConfig()
    assert cfg.min_kappa == LabelingProtocolConfig.min_kappa
    assert cfg.min_codeterminate == LabelingProtocolConfig.min_pairs


def test_evaluate_ok_with_human_corpus() -> None:
    provenance = CorpusProvenanceConfig(min_items=2)
    verdict = evaluate_against_baseline(
        _report(),
        JudgeBaselineConfig(min_codeterminate=10, min_kappa=0.6),
        corpus=_human_corpus(2),
        provenance=provenance,
    )
    assert verdict.ok is True
    assert verdict.problems == ()


def test_evaluate_fails_closed_on_may_gate_kappa_n_and_missing_corpus() -> None:
    report = _report(agreement_may_gate=False, kappa=0.1, n_codeterminate=2)
    verdict = evaluate_against_baseline(report, JudgeBaselineConfig())
    assert verdict.ok is False
    joined = " ".join(verdict.problems)
    assert "may_gate" in joined
    assert "min_kappa" in joined
    assert "n_codeterminate" in joined
    assert "no corpus" in joined


def test_synthetic_corpus_cannot_underwrite() -> None:
    corpus = GoldenSet(
        (
            GoldenItem("a", "t", 1, meta={"provenance": "synthetic"}),
            GoldenItem("b", "t", 0, meta={"provenance": "synthetic"}),
        )
    )
    verdict = evaluate_against_baseline(
        _report(),
        JudgeBaselineConfig(min_codeterminate=1),
        corpus=corpus,
        provenance=CorpusProvenanceConfig(min_items=2),
    )
    assert verdict.ok is False
    assert any("synthetic" in p for p in verdict.problems)


def test_cli_round_trip(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    report_path = tmp_path / "r.json"
    corpus_path = tmp_path / "c.jsonl"
    dump_judge_calibration_report(_report(), report_path)
    corpus_path.write_text(_human_corpus(2).to_jsonl(), encoding="utf-8")
    assert (
        main(
            [
                "--report",
                str(report_path),
                "--corpus",
                str(corpus_path),
                "--min-codeterminate",
                "2",
            ]
        )
        == 2
    )  # default min_items=50
    assert "FAIL" in capsys.readouterr().err
    assert (
        main(
            [
                "--report",
                str(report_path),
                "--allow-synthetic-corpus",
                "--min-codeterminate",
                "2",
            ]
        )
        == 0
    )
    assert "PASS" in capsys.readouterr().out


def test_invalid_min_codeterminate() -> None:
    with pytest.raises(ConfigError):
        JudgeBaselineConfig(min_codeterminate=0)
    with pytest.raises(ConfigError):
        JudgeBaselineConfig(min_kappa=1.5)


def test_cli_missing_report_is_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "absent.json"
    assert main(["--report", str(missing)]) == 2
    assert "FAIL" in capsys.readouterr().err
