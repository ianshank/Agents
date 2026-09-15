#!/usr/bin/env python3
"""Generate the frozen synthetic answer-quality corpus at ``corpora/answer_quality/v1/``.

Strata: citation miss, source selection, multi-hop, numerical claim, ambiguity,
unrecovered tool error, poisoned/stale retrieval. Scorers reused: ``req_scope_hallucination``
and ``trajectory_recovery``. Generated, never scraped.

Usage::

    python scripts/gen_answer_quality_corpus.py --write
    python scripts/gen_answer_quality_corpus.py --check
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from _answer_quality_corpus_lib import (
    GENERATOR_SEED,
    HOLDOUT_FRACTION,
    SCHEMA_VERSION,
    build_items,
    item_hash,
)
from _cli import configure_logging

logger = logging.getLogger(__name__)

_HERE = Path(__file__).resolve().parent
REPO_ROOT = _HERE.parent
CORPUS_DIR = REPO_ROOT / "corpora" / "answer_quality" / "v1"


def _trajectory_steps(unrecovered: bool) -> list[dict[str, Any]]:
    search = {"name": "search", "arguments": {"q": "policy"}}
    fetch = {"name": "fetch", "arguments": {"url": "https://example.invalid/policy"}}
    steps: list[dict[str, Any]] = [
        {"kind": "tool_call", "tool_call": search},
        {"kind": "tool_observation", "tool_call": search, "content": "doc"},
        {"kind": "tool_call", "tool_call": fetch},
    ]
    if unrecovered:
        steps.append({"kind": "tool_error", "tool_call": fetch, "content": "timeout"})
        steps.append({"kind": "final", "content": "answered anyway"})
    else:
        steps.append({"kind": "tool_observation", "tool_call": fetch, "content": "body"})
        steps.append({"kind": "final", "content": "answered"})
    return steps


def _eval_record(item: dict[str, Any]) -> dict[str, Any]:
    freshness = "sensitive" if item["unrecovered_tool_error"] else "normal"
    return {
        "id": item["item_id"],
        "inputs": {
            "question": item["question"],
            "evidence_sources": item["evidence_sources"],
            "generated": item["generated"],
        },
        "expected": {"tool_calls": ["search", "fetch"]},
        "metadata": {
            "stratum": item["stratum"],
            "split": item["split"],
            "gold_ac": item["gold_ac"],
            "replay_tags": {"stratum": item["stratum"], "freshness": freshness},
        },
    }


def _envelope(item: dict[str, Any]) -> dict[str, Any]:
    from eval_harness.core.types import REQUIREMENTS_EVIDENCE_KEY, TRAJECTORY_SCHEMA_VERSION, AgentTrajectory
    from eval_harness.replay.envelope import (
        ReplayEnvelope,
        canonical_hash,
        envelope_to_dict,
        trajectory_from_dict,
    )

    steps_raw = {
        "schema_version": TRAJECTORY_SCHEMA_VERSION,
        "steps": _trajectory_steps(item["unrecovered_tool_error"]),
    }
    trajectory = trajectory_from_dict(steps_raw)
    assert isinstance(trajectory, AgentTrajectory)
    output = item["generated"]
    evidence = [{"source_id": sid} for sid in item["recorded_source_ids"]]
    freshness = "sensitive" if item["unrecovered_tool_error"] else "normal"
    env = ReplayEnvelope(
        envelope_id=f"env-{item['item_id']}",
        recorded_run_id="answer-quality-v1",
        item_id=item["item_id"],
        recorded_at="2026-09-14T00:00:00+00:00",
        environment="offline-corpus",
        agent_version="corpus-1",
        input_hash=canonical_hash(item["question"]),
        output_hash=canonical_hash(output),
        trajectory=trajectory,
        output=output,
        output_metadata={REQUIREMENTS_EVIDENCE_KEY: evidence},
        tags={"stratum": item["stratum"], "freshness": freshness},
    )
    return envelope_to_dict(env)


def build_manifest(items: list[dict[str, Any]]) -> dict[str, Any]:
    strata: dict[str, int] = {}
    splits: dict[str, int] = {}
    for item in items:
        strata[item["stratum"]] = strata.get(item["stratum"], 0) + 1
        splits[item["split"]] = splits.get(item["split"], 0) + 1
    return {
        "schema_version": SCHEMA_VERSION,
        "generator": "scripts/gen_answer_quality_corpus.py",
        "generator_seed": GENERATOR_SEED,
        "holdout_fraction": HOLDOUT_FRACTION,
        "item_count": len(items),
        "strata": dict(sorted(strata.items())),
        "splits": dict(sorted(splits.items())),
        "items": {item["item_id"]: item_hash(item) for item in items},
    }


def generated_artifacts(items: list[dict[str, Any]] | None = None) -> dict[str, str]:
    payload = items if items is not None else build_items()
    eval_lines = [json.dumps(_eval_record(item), sort_keys=True) for item in payload]
    env_lines = [json.dumps(_envelope(item), sort_keys=True) for item in payload]
    return {
        "items.json": json.dumps(payload, indent=2, sort_keys=True) + "\n",
        "manifest.json": json.dumps(build_manifest(payload), indent=2, sort_keys=True) + "\n",
        "eval/items.jsonl": "\n".join(eval_lines) + "\n",
        "eval/envelopes.jsonl": "\n".join(env_lines) + "\n",
    }


def write_corpus(root: Path, items: list[dict[str, Any]] | None = None) -> None:
    for relative, body in generated_artifacts(items).items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")


def check_corpus(directory: Path) -> list[str]:
    problems: list[str] = []
    for relative, expected in generated_artifacts().items():
        path = directory / relative
        if not path.exists():
            problems.append(f"{path.as_posix()} is missing")
        elif path.read_text(encoding="utf-8") != expected:
            problems.append(f"{path.as_posix()} differs from a fresh generation — regenerate with --write")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true")
    group.add_argument("--check", action="store_true")
    parser.add_argument("--dir", default=str(CORPUS_DIR), help="corpus directory")
    args = parser.parse_args(argv)
    configure_logging()
    directory = Path(args.dir)
    if args.write:
        write_corpus(directory)
        logger.info("wrote corpus to %s", directory)
        return 0
    problems = check_corpus(directory)
    for problem in problems:
        logger.error("%s", problem)
    if not problems:
        logger.info("answer_quality corpus matches a fresh generation")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
