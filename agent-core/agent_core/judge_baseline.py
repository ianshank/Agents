"""Compare a :class:`JudgeCalibrationReport` to documented activation floors.

Does not replace :attr:`JudgeCalibrationReport.may_gate` -- that verdict is the
probe/agreement composition. This module adds the *corpus* obligation (human
labels at a protocol floor) so a report built on synthetic pairs cannot authorise
a blocking gate.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from .config import ConfigError
from .corpus_provenance import CorpusProvenanceConfig, require_human_corpus
from .golden import GoldenSet
from .judge_calibration_report import JudgeCalibrationReport, load_judge_calibration_report
from .labeling_protocol import LabelingProtocolConfig
from .logging_util import configure_from_config, debug_span, get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class JudgeBaselineConfig:
    """Floors a report must clear *in addition to* ``may_gate``.

    Kappa / pair-count defaults are the labeling protocol's, so the two cannot
    drift apart. ``require_may_gate`` defaults True: a biased judge is not saved
    by a large human corpus.
    """

    min_kappa: float = LabelingProtocolConfig.min_kappa
    min_codeterminate: int = LabelingProtocolConfig.min_pairs
    require_may_gate: bool = True
    require_human_corpus: bool = True

    def __post_init__(self) -> None:
        if not 0.0 <= self.min_kappa <= 1.0:
            raise ConfigError("judge_baseline.min_kappa must be in [0, 1]")
        if self.min_codeterminate < 1:
            raise ConfigError("judge_baseline.min_codeterminate must be >= 1")


@dataclass(frozen=True)
class BaselineVerdict:
    ok: bool
    problems: tuple[str, ...]


def evaluate_against_baseline(
    report: JudgeCalibrationReport,
    cfg: JudgeBaselineConfig | None = None,
    *,
    corpus: GoldenSet | None = None,
    provenance: CorpusProvenanceConfig | None = None,
) -> BaselineVerdict:
    """Return problems rather than raising, so a CLI can print them all."""
    conf = cfg or JudgeBaselineConfig()
    problems: list[str] = []
    with debug_span(logger, "evaluate_against_baseline", judge=report.judge_id):
        if conf.require_may_gate and not report.may_gate:
            problems.append(f"report.may_gate is False (failing_checks={report.failing_checks})")
        if report.kappa is None or report.kappa < conf.min_kappa:
            problems.append(
                f"kappa {report.kappa!r} is below min_kappa={conf.min_kappa}"
            )
        if report.n_codeterminate < conf.min_codeterminate:
            problems.append(
                f"n_codeterminate={report.n_codeterminate} < min_codeterminate="
                f"{conf.min_codeterminate}"
            )
        if conf.require_human_corpus:
            if corpus is None:
                problems.append("require_human_corpus is set but no corpus was provided")
            else:
                try:
                    require_human_corpus(corpus, provenance)
                except ConfigError as exc:
                    problems.append(str(exc))
    verdict = BaselineVerdict(ok=not problems, problems=tuple(problems))
    logger.info(
        "judge-baseline judge=%s ok=%s problems=%d",
        report.judge_id,
        verdict.ok,
        len(verdict.problems),
    )
    return verdict


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Assert a judge calibration report meets baselines.")
    ap.add_argument("--report", required=True, help="JudgeCalibrationReport JSON path")
    ap.add_argument("--corpus", help="optional GoldenSet JSONL (required when human corpus is on)")
    ap.add_argument(
        "--min-kappa",
        type=float,
        default=JudgeBaselineConfig.min_kappa,
    )
    ap.add_argument(
        "--min-codeterminate",
        type=int,
        default=JudgeBaselineConfig.min_codeterminate,
    )
    ap.add_argument(
        "--allow-synthetic-corpus",
        action="store_true",
        help="skip the human-corpus obligation (debug only; default is require human)",
    )
    args = ap.parse_args(argv)
    configure_from_config()
    cfg = JudgeBaselineConfig(
        min_kappa=args.min_kappa,
        min_codeterminate=args.min_codeterminate,
        require_human_corpus=not args.allow_synthetic_corpus,
    )
    try:
        report = load_judge_calibration_report(Path(args.report))
        corpus = None
        if args.corpus:
            corpus = GoldenSet.from_jsonl(Path(args.corpus).read_text(encoding="utf-8"))
        verdict = evaluate_against_baseline(report, cfg, corpus=corpus)
    except (OSError, ValueError, TypeError, ConfigError) as exc:
        logger.error("judge-baseline: %s", exc)
        print(f"judge-baseline FAIL: {exc}", file=sys.stderr)
        return 2
    if not verdict.ok:
        for problem in verdict.problems:
            print(f"judge-baseline FAIL: {problem}", file=sys.stderr)
        return 2
    print(f"judge-baseline PASS judge={report.judge_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
