"""Command-line entry point for a deterministic, offline behavioural-regression run.

Examples::

    bregress --seed 7 --out out/report.json
    bregress --seed 7 --set v2_sycophancy_mean=0.55 --html out/report.html

No network is used on this path. ``--set key=value`` overrides any ``BRConfig`` field;
values are coerced (bool/int/float/str), so nothing is hardcoded at the call site.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from agent_core.logging_util import get_logger

from .config import BRConfig
from .pipeline import run_pipeline

_log = get_logger("behavioral_regression.cli")


def _coerce(value: str) -> Any:
    """Coerce a CLI string to bool/int/float, falling back to the raw string."""
    low = value.lower()
    if low in ("true", "false"):
        return low == "true"
    for cast in (int, float):
        try:
            return cast(value)
        except ValueError:
            continue
    return value


def _build_config(overrides: Sequence[str]) -> BRConfig:
    fields: dict[str, Any] = {}
    for item in overrides:
        if "=" not in item:
            raise ValueError(f"--set expects key=value, got {item!r}")
        key, raw = item.split("=", 1)
        fields[key.strip()] = _coerce(raw.strip())
    # from_dict validates unknown keys and migrates, so a bad --set yields a clean
    # ConfigError instead of a raw TypeError traceback.
    return BRConfig.from_dict(fields)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bregress", description=__doc__)
    parser.add_argument("--seed", type=int, default=7, help="deterministic run seed")
    parser.add_argument("--out", type=str, default=None, help="write the JSON report here")
    parser.add_argument("--html", type=str, default=None, help="write the HTML report here")
    parser.add_argument(
        "--set",
        dest="overrides",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="override a BRConfig field (repeatable)",
    )
    args = parser.parse_args(argv)

    cfg = _build_config(args.overrides)
    _log.info("behavioral-regression run starting: seed=%d", args.seed)
    report = run_pipeline(cfg, seed=args.seed)
    payload = json.dumps(report.to_dict(), sort_keys=True, separators=(",", ":"))

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(payload + "\n", encoding="utf-8")
        _log.info("wrote JSON report to %s", args.out)
    else:
        print(payload)
    if args.html:
        Path(args.html).parent.mkdir(parents=True, exist_ok=True)
        Path(args.html).write_text(report.to_html(), encoding="utf-8")
        _log.info("wrote HTML report to %s", args.html)

    _log.info("behavioural-regression decision: %s", report.decision.value)
    print(f"decision: {report.decision.value}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
