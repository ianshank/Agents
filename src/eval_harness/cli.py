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
from .phoenix_client import configure_tracing
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

    compare = sub.add_parser("compare", help="run a multi-model comparison from a config with a 'comparison' block")
    compare.add_argument("--config", required=True, help="path to the eval config YAML")
    compare.add_argument(
        "--set",
        dest="overrides",
        action="append",
        default=[],
        metavar="KEY.PATH=VALUE",
        help="override a config value (repeatable)",
    )
    compare.add_argument("--offline", action="store_true", help="use an in-memory Langfuse client")
    compare.add_argument("--html", dest="html_out", help="write the comparison report here (HTML)")
    compare.add_argument("--json", dest="json_out", help="write the comparison result here (JSON)")

    campaign = sub.add_parser("campaign", help="run or analyze an A/B eval campaign (config 'ab_campaign' block)")
    campaign.add_argument("--config", required=True, help="path to the eval config YAML")
    campaign.add_argument("--store", required=True, help="append-only JSONL campaign store")
    campaign.add_argument("--mode", choices=["record", "analyze"], default="record")
    campaign.add_argument("--set", dest="overrides", action="append", default=[], metavar="KEY.PATH=VALUE")
    campaign.add_argument("--offline", action="store_true", help="use an in-memory Langfuse client")
    campaign.add_argument("--html", dest="html_out", help="write the analysis report here (HTML)")
    campaign.add_argument("--json", dest="json_out", help="write the analysis result here (JSON)")

    sub.add_parser("list-plugins", help="list all registered components")
    return parser


def _cmd_run(args: argparse.Namespace) -> int:
    config = load_config(args.config, overrides=args.overrides)
    # Opt-in Phoenix tracing: gated inside configure_tracing (no-op when config.phoenix
    # is absent/disabled or the SDK is missing), so this is safe and additive.
    configure_tracing(config.phoenix)
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


def _cmd_compare(args: argparse.Namespace) -> int:
    import json as _json

    from .comparison import run_comparison

    config = load_config(args.config, overrides=args.overrides)
    if config.comparison is None:
        print("ERROR: config has no 'comparison' block; nothing to compare", file=sys.stderr)
        return 2
    client: LangfuseClient = NullLangfuseClient()
    if not args.offline:
        from .langfuse_client import SDKLangfuseClient

        client = SDKLangfuseClient()

    result = run_comparison(config, langfuse_client=client)
    if args.html_out:
        with open(args.html_out, "w", encoding="utf-8") as fh:
            fh.write(result.to_html(title=config.run.name))
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            _json.dump(result.to_dict(), fh, indent=2, sort_keys=True)

    print(f"ranked by {result.rank_by} ({result.rank_metric}): {' > '.join(result.overall_ranking)}")
    return 0


def _cmd_campaign(args: argparse.Namespace) -> int:
    import json as _json

    from .campaign import CampaignStore, analyze, record_run

    config = load_config(args.config, overrides=args.overrides)
    if config.ab_campaign is None:
        print("ERROR: config has no 'ab_campaign' block; nothing to run", file=sys.stderr)
        return 2
    store = CampaignStore(args.store)

    if args.mode == "record":
        client: LangfuseClient = NullLangfuseClient()
        if not args.offline:
            from .langfuse_client import SDKLangfuseClient

            client = SDKLangfuseClient()
        recs = record_run(store, config, langfuse_client=client)
        for r in recs:
            print(f"recorded {r.arm}: {r.successes}/{r.n} on {r.score}")
        return 0

    result = analyze(store, config.ab_campaign)
    if args.html_out:
        with open(args.html_out, "w", encoding="utf-8") as fh:
            fh.write(result.to_html())
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            _json.dump(result.to_dict(), fh, indent=2, sort_keys=True)
    print(f"decision: {result.decision.value} (delta={result.delta})")
    return 0


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
    if args.command == "compare":
        return _cmd_compare(args)
    if args.command == "campaign":
        return _cmd_campaign(args)
    if args.command == "list-plugins":
        return _cmd_list(args)
    return 2  # pragma: no cover - argparse enforces a command


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
