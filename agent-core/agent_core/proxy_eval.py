"""Proxy-correlation measurement for prediction-powered audit estimates.

Answers the question that governs whether borrowing statistical strength is worth
wiring at all: **how well does a cheap, always-available proxy predict the expensive,
authoritative HUMAN_AUDIT label — on the subsets the gate actually operates over?**

Read-only: nothing here writes to the store or influences a gate decision.

Proxies are pluggable via :class:`ProxyExtractor`, so adding one (for example an LLM
judge's score) needs no change here and no new dependency — ``agent_core`` stays
dependency-free, and external scores arrive through :class:`MappingProxy`.

Run as a module::

    python -m agent_core.proxy_eval --store merge_outcomes.jsonl \
        [--domain-filter agent|human|all] [--judge-scores scores.json] [--format md|json]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from .config import ConfigError
from .domains import DOMAIN_FILTERS
from .logging_util import debug_span, get_logger
from .outcome_store import OutcomeStore
from .proxy_analysis import ProxyEvalConfig, analyze_dataset
from .proxy_dataset import build_dataset
from .proxy_render import render_json, render_markdown

# Re-exported (`X as X` is mypy's explicit re-export form) so the proxies stay importable
# from here after being split into `agent_core.proxies`.
from .proxies import MappingProxy as MappingProxy
from .proxies import PassiveLabelProxy as PassiveLabelProxy
from .proxies import ProxyExtractor as ProxyExtractor
from .proxies import RawConfidenceProxy as RawConfidenceProxy

logger = get_logger(__name__)


def default_extractors(judge_scores: Mapping[str, float] | None = None) -> list[ProxyExtractor]:
    """The proxies evaluated when a caller does not supply its own set."""
    extractors: list[ProxyExtractor] = [RawConfidenceProxy(), PassiveLabelProxy()]
    if judge_scores:
        extractors.append(MappingProxy("judge_score", dict(judge_scores)))
    return extractors


def evaluate_store(
    store: OutcomeStore,
    extractors: Sequence[ProxyExtractor] | None = None,
    cfg: ProxyEvalConfig | None = None,
    *,
    domain_filter: str = "agent",
) -> list:
    """Build and analyse a dataset per proxy. Read-only over the store."""
    cfg = cfg or ProxyEvalConfig()
    chosen = list(extractors) if extractors is not None else default_extractors()
    if not store.path.exists():
        logger.warning(
            "outcome store %s does not exist -- reporting empty slices (is --store right?)",
            store.path,
        )
    reports: list = []
    with debug_span(logger, "evaluate_store", proxies=len(chosen), domain_filter=domain_filter):
        for extractor in chosen:
            dataset = build_dataset(store, extractor, domain_filter=domain_filter)
            reports.append(analyze_dataset(dataset, cfg))
    return reports


def _load_judge_scores(path: str | None) -> dict[str, float] | None:
    """Load ``{change_id: score}`` from JSON. The external-proxy seam."""
    if path is None:
        return None
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError(f"judge scores must be a JSON object of change_id -> score ({path})")
    out: dict[str, float] = {}
    for k, v in raw.items():
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(float(v)):
            raise ConfigError(f"judge score for {k!r} must be a finite number (got {v!r})")
        out[str(k)] = float(v)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Proxy-correlation report for audit estimates.")
    ap.add_argument("--store", required=True)
    ap.add_argument("--domain-filter", choices=list(DOMAIN_FILTERS), default="agent")
    ap.add_argument("--format", choices=["md", "json"], default="md")
    defaults = ProxyEvalConfig()
    ap.add_argument("--n-bins", type=int, default=defaults.n_bins)
    ap.add_argument("--z", type=float, default=defaults.z)
    ap.add_argument("--min-pairs", type=int, default=defaults.min_pairs)
    ap.add_argument(
        "--judge-scores",
        default=None,
        help="JSON file of {change_id: score} adding an external proxy (e.g. an LLM judge)",
    )
    ap.add_argument("--output", help="write here instead of stdout")
    args = ap.parse_args(argv)

    try:
        cfg = ProxyEvalConfig(n_bins=args.n_bins, z=args.z, min_pairs=args.min_pairs)
        judge = _load_judge_scores(args.judge_scores)
    except (ConfigError, OSError, json.JSONDecodeError) as exc:
        logger.error("invalid proxy-eval configuration: %s", exc)
        return 2

    reports = evaluate_store(
        OutcomeStore(args.store),
        default_extractors(judge),
        cfg,
        domain_filter=args.domain_filter,
    )
    text = render_json(reports, cfg) if args.format == "json" else render_markdown(reports, cfg)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
