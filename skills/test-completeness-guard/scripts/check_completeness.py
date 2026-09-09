#!/usr/bin/env python3
"""Census frozen public-surface names against a test tree.

Does not invent a product coverage floor. A positive ``--min-hit-rate`` is an
explicit caller choice; the default is report-only (0.0).
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("check-completeness")


@dataclass(frozen=True)
class CompletenessConfig:
    """Hit-rate floor. Zero means report-only; callers who want a gate pass a value."""

    min_hit_rate: float = 0.0
    json_indent: int = 2


DEFAULT_CONFIG = CompletenessConfig()


@dataclass(frozen=True)
class CompletenessReport:
    baseline: str
    tests: str
    exported: int
    mentioned: int
    missing: tuple[str, ...]
    hit_rate: float
    min_hit_rate: float
    passed: bool


def _configure_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


def baseline_names(payload: Mapping[str, object]) -> frozenset[str]:
    names: set[str] = set()
    surface = payload.get("surface")
    if isinstance(surface, dict):
        for values in surface.values():
            if isinstance(values, list):
                names.update(str(v) for v in values)
    components = payload.get("components")
    if isinstance(components, dict):
        for values in components.values():
            if isinstance(values, list):
                names.update(str(v) for v in values)
    return frozenset(names)


def load_baseline(path: Path) -> frozenset[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CompletenessUsageError(f"cannot read baseline {path.as_posix()}: {exc}") from exc
    if not isinstance(data, dict):
        raise CompletenessUsageError(f"{path.as_posix()} is not a JSON object")
    return baseline_names(data)


def test_files(test_root: Path) -> tuple[Path, ...]:
    if not test_root.is_dir():
        raise CompletenessUsageError(f"tests directory not found: {test_root.as_posix()}")
    found = sorted(p for p in test_root.rglob("test_*.py") if p.is_file())
    return tuple(found)


def mentioned_names(files: Iterable[Path], names: frozenset[str]) -> frozenset[str]:
    if not names:
        return frozenset()
    blobs: list[str] = []
    for path in files:
        try:
            blobs.append(path.read_text(encoding="utf-8"))
        except OSError as exc:
            logger.warning("skipping unreadable test file %s (%s)", path.as_posix(), exc)
    blob = "\n".join(blobs)
    hit: set[str] = set()
    for name in names:
        if re.search(rf"\b{re.escape(name)}\b", blob):
            hit.add(name)
    return frozenset(hit)


def hit_rate(mentioned: int, exported: int) -> float:
    if exported <= 0:
        return 0.0
    return mentioned / exported


def evaluate(
    *,
    baseline: Path,
    tests: Path,
    min_hit_rate: float = DEFAULT_CONFIG.min_hit_rate,
) -> CompletenessReport:
    exported = load_baseline(baseline)
    files = test_files(tests)
    mentioned = mentioned_names(files, exported)
    missing = tuple(sorted(exported - mentioned))
    rate = hit_rate(len(mentioned), len(exported))
    passed = bool(exported) and rate >= min_hit_rate
    return CompletenessReport(
        baseline=baseline.as_posix(),
        tests=tests.as_posix(),
        exported=len(exported),
        mentioned=len(mentioned),
        missing=missing,
        hit_rate=rate,
        min_hit_rate=min_hit_rate,
        passed=passed,
    )


class CompletenessUsageError(ValueError):
    """Missing/unreadable inputs."""


def render_text(report: CompletenessReport) -> str:
    status = "PASS" if report.passed else "FAIL"
    return (
        f"test-completeness-guard: {status} "
        f"{report.mentioned}/{report.exported} names mentioned "
        f"(hit_rate={report.hit_rate:.3f}, floor={report.min_hit_rate:.3f})"
    )


def render_json(report: CompletenessReport, *, indent: int = DEFAULT_CONFIG.json_indent) -> str:
    payload = {
        "baseline": report.baseline,
        "tests": report.tests,
        "exported": report.exported,
        "mentioned": report.mentioned,
        "missing": list(report.missing),
        "hit_rate": report.hit_rate,
        "min_hit_rate": report.min_hit_rate,
        "passed": report.passed,
    }
    return json.dumps(payload, indent=indent, sort_keys=True) + "\n"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--tests", type=Path, required=True)
    parser.add_argument(
        "--min-hit-rate",
        type=float,
        default=DEFAULT_CONFIG.min_hit_rate,
        help="Fail when mentioned/exported is below this floor (default: report-only)",
    )
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    _configure_logging(args.verbose)
    try:
        report = evaluate(baseline=args.baseline, tests=args.tests, min_hit_rate=args.min_hit_rate)
    except CompletenessUsageError as exc:
        print(f"test-completeness-guard: {exc}", file=sys.stderr)
        return 2
    text = render_json(report) if args.format == "json" else render_text(report) + "\n"
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text if args.format == "json" else render_json(report), encoding="utf-8")
    sys.stdout.write(text if args.format == "json" else render_text(report) + "\n")
    if not report.passed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
