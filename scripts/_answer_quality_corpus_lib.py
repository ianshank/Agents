"""Generation library for the synthetic answer-quality corpus.

Deterministic: every choice flows from ``seed:item_id``. Split uses the keyed
``sha256`` idiom (F-011 airgap: not an import of ``flow_corpus``).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

STRATA: tuple[str, ...] = (
    "citation_miss",
    "source_selection",
    "multi_hop",
    "numerical",
    "ambiguity",
    "unrecovered_tool_error",
    "poisoned_stale",
)

GENERATOR_SEED = 20260914
HOLDOUT_FRACTION = 0.25
ITEMS_PER_STRATUM = 2
SCHEMA_VERSION = "1.0"


def bucket(seed: int, key: str) -> float:
    digest = hashlib.sha256(f"{seed}:{key}".encode()).hexdigest()
    return int(digest[:8], 16) / 0x100000000


def item_hash(item: dict[str, Any]) -> str:
    payload = json.dumps(item, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _sources(item_id: str, *, extra_stale: bool = False) -> list[dict[str, Any]]:
    sources = [
        {
            "source_id": f"src-{item_id}-fresh",
            "source_type": "doc",
            "supports": ["freshness", "count_12"],
            "refutes": [],
        }
    ]
    if extra_stale:
        sources.append(
            {
                "source_id": f"src-{item_id}-stale",
                "source_type": "doc",
                "supports": [],
                "refutes": ["freshness"],
            }
        )
    return sources


def build_item(stratum: str, ordinal: int, seed: int) -> dict[str, Any]:
    item_id = f"aq-{stratum}-{ordinal:02d}"
    split = "holdout" if bucket(seed, item_id) < HOLDOUT_FRACTION else "train"
    sources = _sources(item_id, extra_stale=stratum in {"source_selection", "ambiguity", "poisoned_stale"})
    recorded = [src["source_id"] for src in sources]
    claim = "freshness"
    cited = recorded[:1]
    if stratum == "citation_miss":
        cited = [f"src-{item_id}-ghost"]
    elif stratum == "source_selection":
        cited = [f"src-{item_id}-stale"]
    elif stratum == "multi_hop":
        sources.append(
            {
                "source_id": f"src-{item_id}-hop",
                "source_type": "doc",
                "supports": ["freshness"],
                "refutes": [],
            }
        )
        recorded = [sources[0]["source_id"]]
        cited = [sources[0]["source_id"]]
    elif stratum == "numerical":
        claim = "count_99"
        cited = recorded[:1]
    elif stratum == "ambiguity":
        cited = [f"src-{item_id}-fresh"]
        claim = "freshness"
    elif stratum == "poisoned_stale":
        cited = [f"src-{item_id}-stale"]
        claim = "freshness"
    requirements = [
        {
            "id": f"{item_id}-r0",
            "claim": claim,
            "evidence_links": cited,
            "text": f"Answer claims {claim} for {item_id}.",
        }
    ]
    unrecovered = stratum == "unrecovered_tool_error"
    return {
        "item_id": item_id,
        "stratum": stratum,
        "split": split,
        "question": f"What is the current policy for {item_id}?",
        "evidence_sources": sources,
        "recorded_source_ids": recorded,
        "generated": {"requirements": requirements},
        "unrecovered_tool_error": unrecovered,
        "gold_ac": [{"id": f"ac-{item_id}", "text": "cite a recorded fresh source"}],
    }


def build_items() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for stratum in STRATA:
        for ordinal in range(ITEMS_PER_STRATUM):
            items.append(build_item(stratum, ordinal, GENERATOR_SEED))
    return items
