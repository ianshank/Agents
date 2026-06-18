"""Command-line entry point.

    eval-harness run --config config/eval.example.yaml --set run.sample_rate=1.0

Exits non-zero when the quality gate fails, so it drops straight into CI.
"""
from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from .config import load_config
from .engine import EvalEngine
from .gating import evaluate_gate
from .langfuse_client import LangfuseClient, NullLangfuseClient
from .plugins import bootstrap
from .version import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="eval-harness")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run an evaluation from a config file")
    run.add_argument("--config", required=True, help="path to the eval config YAML")
    run.add_argument(
        "--set",
        dest="overrides",
        action="append",
        default=[],
        metavar="KEY.PATH=VALUE",
        help="override a config value (repeatable)",
    )
    run.add_argument(
        "--offline",
        action="store_true",
        help="use an in-memory Langfuse client (no network)",
    )

    sub.add_parser("list-plugins", help="list all registered components")
    return parser


def _cmd_run(args: argparse.Namespace) -> int:
    config = load_config(args.config, overrides=args.overrides)
    client: LangfuseClient
    if args.offline:
        client = NullLangfuseClient()
    else:
        from .langfuse_client import SDKLangfuseClient
        client = SDKLangfuseClient()
    engine = EvalEngine.from_config(config, langfuse_client=client)
    run = engine.run()

    if not any(s.type in ("console",) for s in config.sinks):
        for name, agg in run.aggregate.items():
            pr = "n/a" if agg.pass_rate is None else f"{agg.pass_rate:.2f}"
            print(f"{name}: mean={agg.mean:.3f} pass_rate={pr} n={agg.count}")

    gate = evaluate_gate(config.gate, run)
    if gate.passed:
        print("QUALITY GATE: PASS")
        return 0
    print("QUALITY GATE: FAIL")
    for f in gate.failures:
        print(f"  - {f}")
    return 1


def _cmd_list(_: argparse.Namespace) -> int:
    from .plugins import DATASETS, JUDGES, SCORERS, SINKS, TARGETS

    bootstrap()
    for reg in (SCORERS, DATASETS, TARGETS, SINKS, JUDGES):
        print(f"{reg.kind}s: {', '.join(reg.names())}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "run":
        return _cmd_run(args)
    if args.command == "list-plugins":
        return _cmd_list(args)
    return 2  # pragma: no cover - argparse enforces a command


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
