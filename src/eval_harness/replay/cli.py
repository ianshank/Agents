"""Argparse helpers for ``eval-harness replay``. Dispatched from ``eval_harness.cli``."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from typing import Any

from ..core._paths import OUTPUT_ROOT_ENV, resolve_confined_path
from ..core.types import EvalItem, ItemResult, RunContext, ScoreResult, TargetOutput
from ..plugins import SCORERS, bootstrap
from .archive import ReplayArchive
from .envelope import ReplayConfig, ReplayEnvelope, ReplayError
from .report import failing_steps, render_html, render_text
from .slice import global_pass_rate, pass_rates_by_tag
from .target import ReplayTarget


def add_replay_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser(
        "replay",
        help="re-score recorded AgentTrajectory envelopes (exact or counterfactual)",
    )
    parser.add_argument("--archive", required=True, help="JSONL envelope archive")
    parser.add_argument(
        "--mode",
        choices=ReplayConfig().allowed_modes,
        default=ReplayConfig().mode,
        help="exact re-emits the recording; counterfactual swaps declared tool observations",
    )
    parser.add_argument(
        "--override",
        action="append",
        default=[],
        metavar="tool.name=VALUE",
        help="counterfactual observation replacement (repeatable)",
    )
    parser.add_argument(
        "--from-span",
        dest="from_span",
        default=None,
        help="apply overrides after this span_id, tool name, or step index",
    )
    parser.add_argument(
        "--override-when",
        dest="override_when",
        default=None,
        metavar="tag=value",
        help="restrict overrides to envelopes whose tags match",
    )
    parser.add_argument("--html", dest="html_out", help="write an HTML step table here")
    parser.add_argument("--json", dest="json_out", help="write JSON summary here")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="accepted for demo parity; replay never networks",
    )
    parser.add_argument(
        "--slice-tag",
        dest="slice_tag",
        default=None,
        help="tag key for slice pass-rates (default: ReplayConfig.override_tag_key)",
    )


def parse_overrides(raw: Sequence[str], *, prefix: str | None = None) -> dict[str, str]:
    cfg = ReplayConfig()
    key_prefix = cfg.override_key_prefix if prefix is None else prefix
    parsed: dict[str, str] = {}
    for item in raw:
        if "=" not in item:
            raise ReplayError(f"override must be KEY=VALUE, got {item!r}")
        key, _, value = item.partition("=")
        name = key[len(key_prefix) :] if key.startswith(key_prefix) else key
        if not name:
            raise ReplayError(f"override tool name is empty in {item!r}")
        parsed[name] = value
    return parsed


def parse_tag_filter(raw: str | None) -> tuple[str | None, str]:
    if raw is None or raw == "":
        return None, ""
    if "=" not in raw:
        raise ReplayError(f"override-when must be tag=value, got {raw!r}")
    key, _, value = raw.partition("=")
    if not key:
        raise ReplayError("override-when tag key is empty")
    return key, value


def _expected_tool_calls(envelope: ReplayEnvelope) -> list[dict[str, Any]]:
    return [{"name": call.name, "arguments": dict(call.arguments)} for call in envelope.trajectory.tool_calls()]


def items_from_envelopes(envelopes: Sequence[ReplayEnvelope]) -> list[EvalItem]:
    items: list[EvalItem] = []
    for envelope in envelopes:
        items.append(
            EvalItem(
                id=envelope.item_id,
                inputs={"envelope_id": envelope.envelope_id},
                expected={"tool_calls": _expected_tool_calls(envelope)},
                metadata={"replay_tags": dict(envelope.tags)},
            )
        )
    return items


def _score_one(item: EvalItem, output: TargetOutput, names: Sequence[str]) -> ItemResult:
    ctx = RunContext(config=None)
    if output.error is not None:
        scores = [ScoreResult(name=name, value=0.0, passed=False, comment=output.error) for name in names]
    else:
        scores = [SCORERS.create(name, {}).score(item, output, ctx) for name in names]
    return ItemResult(item=item, output=output, scores=scores)


def _write(path: str, body: str) -> None:
    resolved = resolve_confined_path(
        path,
        root_env_var=OUTPUT_ROOT_ENV,
        description="replay report path",
        must_exist=False,
    )
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(body, encoding="utf-8")


def _summary_payload(
    results: Sequence[ItemResult],
    *,
    mode: str,
    tag_key: str,
    config: ReplayConfig,
) -> dict[str, Any]:
    passed, n, rate = global_pass_rate(results, config=config)
    slices = pass_rates_by_tag(results, tag_key, config=config)
    return {
        "mode": mode,
        "global": {"passed": passed, "n": n, "pass_rate": rate, "score": config.slice_score},
        "slices": [
            {
                "tag_key": row.tag_key,
                "tag_value": row.tag_value,
                "n": row.n,
                "passed": row.passed,
                "pass_rate": row.pass_rate,
            }
            for row in slices
        ],
        "first_failing_steps": [
            {
                "item_id": step.item_id,
                "index": step.index,
                "kind": step.kind,
                "tool_name": step.tool_name,
                "content": step.content,
            }
            for step in failing_steps(results)
        ],
    }


def run_replay(args: argparse.Namespace) -> int:
    """Load *args.archive*, re-score, print a slice report. Never fetches vendor spans."""
    cfg = ReplayConfig()
    try:
        overrides = parse_overrides(args.override)
        tag_key, tag_value = parse_tag_filter(args.override_when)
    except ReplayError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    bootstrap()
    try:
        envelopes = ReplayArchive(args.archive).load()
    except (ReplayError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    items = items_from_envelopes(envelopes)
    target = ReplayTarget(
        mode=args.mode,
        overrides=overrides,
        from_span=args.from_span,
        override_tag_key=tag_key if tag_key is not None else cfg.override_tag_key,
        override_tag_value=tag_value,
        envelopes=envelopes,
    )
    results = [_score_one(item, target.run(item), cfg.default_scorers) for item in items]
    slice_key = args.slice_tag if args.slice_tag is not None else cfg.override_tag_key
    print(render_text(results, tag_key=slice_key, config=cfg))
    if args.html_out:
        _write(args.html_out, render_html(results, tag_key=slice_key, config=cfg))
    if args.json_out:
        payload = _summary_payload(results, mode=args.mode, tag_key=slice_key, config=cfg)
        _write(args.json_out, json.dumps(payload, indent=2, sort_keys=True))
    _ = args.offline  # documented no-op: replay has no network client
    return 0


def parse_overrides_mapping(raw: Mapping[str, str]) -> dict[str, str]:
    """Normalize a mapping of overrides (tests / YAML)."""
    return parse_overrides([f"{k}={v}" for k, v in raw.items()])
