#!/usr/bin/env python3
"""Generate the frozen synthetic requirements corpus at ``corpora/requirements/v1/``.

Implements ``openspec/changes/add-requirements-gen-eval-matrix`` task 2. Synthetic first
for a methodological reason (that change's design.md): the provenance mechanism must be
proven against sources whose ground truth we control before it is trusted on sources we
cannot re-fetch. Each epic carries an authored gold acceptance-criteria set, a declared
source mix, and the evidence bytes those sources resolve to — so the provenance wrapper's
records and the scorers' grounding checks run fully offline.

Negative controls: contradictory-source items (two evidence sources disagree on the same
point), stale-source items (a source superseded by a newer revision), and
mutated-evidence items (content mutated after capture — the provenance verification pass
must notice). None is distinguishable from an ordinary item by any field the target sees.

Usage::

    python scripts/gen_requirements_corpus.py --write     # (re)generate the frozen corpus
    python scripts/gen_requirements_corpus.py --check     # fail if the committed corpus drifted

Exit codes:
    0 - corpus written, or committed corpus matches a fresh generation
    1 - drift detected under --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import random
import sys
from pathlib import Path
from typing import Any

from _cli import configure_logging

_HERE = Path(__file__).resolve().parent

logger = logging.getLogger(__name__)

REPO_ROOT = _HERE.parent
CORPUS_DIR = REPO_ROOT / "corpora" / "requirements" / "v1"

#: Bumped when the item shape changes in a way a reader must notice.
SCHEMA_VERSION = "1.0"

#: Seed for every deterministic choice below. Recorded in the manifest.
GENERATOR_SEED = 20260906

#: Fraction of items in the sequestered split.
HOLDOUT_FRACTION = 0.24

#: Corpus size (tasks.md 2.1).
ITEM_COUNT = 25

#: The share of items that are negative controls (contradictory / stale / mutated).
#: Ordinary items fill the rest.
CONTROL_FRACTION = 0.36

_DOMAINS = ("billing", "auth", "search", "notify", "reporting")
_AC_TEMPLATES = (
    "when {actor} submits valid input, the system persists it",
    "when {actor} submits invalid input, the system rejects it with a named error",
    "when {actor} is unauthenticated, the system refuses the action",
    "when the backend is unavailable, the system retries with backoff",
    "when two submissions race, the system serialises them deterministically",
    "when the quota is exceeded, the system throttles and reports 429",
)


def _bucket(seed: int, key: str) -> float:
    """The keyed-holdout idiom (sha256 over ``seed:key`` folded into [0, 1))."""
    digest = hashlib.sha256(f"{seed}:{key}".encode()).hexdigest()
    return int(digest[:8], 16) / 0x100000000


def _item_hash(item: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()


def _gold_acs(rng: random.Random, domain: str, count: int) -> list[dict[str, str]]:
    actor = f"{domain} user"
    return [
        {"id": f"ac-{domain}-{i}", "text": _AC_TEMPLATES[i % len(_AC_TEMPLATES)].format(actor=actor)}
        for i in range(count)
    ]


def build_items() -> list[dict[str, Any]]:
    """Every corpus item, deterministically."""
    items: list[dict[str, Any]] = []
    control_count = round(ITEM_COUNT * CONTROL_FRACTION)
    for ordinal in range(ITEM_COUNT):
        rng = random.Random(f"{GENERATOR_SEED}:req-{ordinal:02d}")
        domain = _DOMAINS[ordinal % len(_DOMAINS)]
        epic_id = f"req-{ordinal:02d}"
        gold = _gold_acs(rng, domain, 3 + ordinal % 3)

        # Every item declares two evidence sources; the control class decides what they
        # contain. Source bytes live in the corpus so the offline store can serve them.
        src_a = f"src-{epic_id}-a"
        src_b = f"src-{epic_id}-b"
        base_a = f"The {domain} service persists submissions and reports quota use."
        base_b = f"The {domain} service requires authentication for all actions."

        control = "ordinary"
        if ordinal < control_count:
            control = ("contradictory", "stale", "mutated")[ordinal % 3]
        if control == "contradictory":
            base_b = f"The {domain} service allows anonymous actions."  # contradicts src_a's auth requirement
        elif control == "stale":
            base_b = f"DEPRECATED (rev 1): the {domain} service has no quota."
        elif control == "mutated":
            # The recorded hash is over the ORIGINAL bytes; the store serves mutated ones.
            pass

        evidence = {
            src_a: base_a,
            src_b: base_b,
        }
        sources = [
            {
                "source_type": "drive_doc",
                "source_id": src_a,
                "reference": {"kind": "revision_export_link", "revision_id": f"rev-{epic_id}-a", "mime": "text/plain"},
            },
            {
                "source_type": "drive_doc",
                "source_id": src_b,
                "reference": {"kind": "revision_export_link", "revision_id": f"rev-{epic_id}-b", "mime": "text/plain"},
            },
        ]
        # The mutated control's store bytes differ from what its recorded hash covers.
        store_bytes = dict(evidence)
        recorded_hashes = {sid: hashlib.sha256(data.encode()).hexdigest() for sid, data in evidence.items()}
        if control == "mutated":
            store_bytes[src_b] = base_b + " (edited after capture)"

        items.append(
            {
                "epic_id": epic_id,
                "domain": domain,
                "title": f"{domain.title()} epic {ordinal}",
                "statement": f"As a {domain} owner I need the {domain} workflow hardened.",
                "gold_ac": gold,
                "evidence_sources": sources,
                "evidence_bytes": evidence,
                "store_bytes": store_bytes,
                "recorded_hashes": recorded_hashes,
                "declared_tests": [f"test_{domain}_persists", f"test_{domain}_rejects_invalid"],
                "control": control,
            }
        )
    return items


def build_manifest(items: list[dict[str, Any]]) -> dict[str, Any]:
    classes: dict[str, int] = {}
    splits: dict[str, int] = {}
    for item in items:
        classes[item["control"]] = classes.get(item["control"], 0) + 1
        splits[item["split"]] = splits.get(item["split"], 0) + 1
    return {
        "schema_version": SCHEMA_VERSION,
        "generator": "scripts/gen_requirements_corpus.py",
        "generator_seed": GENERATOR_SEED,
        "holdout_fraction": HOLDOUT_FRACTION,
        "item_count": len(items),
        "classes": dict(sorted(classes.items())),
        "splits": dict(sorted(splits.items())),
        "items": {item["epic_id"]: _item_hash(item) for item in items},
    }


def _dumps(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def build_eval_records(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Harness-loadable records: the epic, its gold set, and its declared evidence.

    ``evidence_bytes``/``store_bytes``/``recorded_hashes`` stay OUT of the inputs — they
    are corpus-internal ground truth the target must not see (the wrapper fetches through
    the store, and the verification pass compares against the recorded hashes).
    """
    return [
        {
            "id": item["epic_id"],
            "inputs": {
                "epic": item["statement"],
                "title": item["title"],
                "evidence_sources": item["evidence_sources"],
                "declared_tests": item["declared_tests"],
            },
            "expected": [ac["id"] for ac in item["gold_ac"]],
            "metadata": {
                "corpus_item": item["epic_id"],
                "control": item["control"],
                "split": item["split"],
                "gold_ac": item["gold_ac"],
            },
        }
        for item in items
    ]


def _with_split(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for item in items:
        item["split"] = "holdout" if _bucket(GENERATOR_SEED, item["epic_id"]) < HOLDOUT_FRACTION else "train"
        out.append(item)
    return out


def write_corpus(directory: Path) -> tuple[Path, Path]:
    items = _with_split(build_items())
    directory.mkdir(parents=True, exist_ok=True)
    items_path = directory / "items.json"
    manifest_path = directory / "manifest.json"
    items_path.write_text(_dumps(items), encoding="utf-8")
    manifest_path.write_text(_dumps(build_manifest(items)), encoding="utf-8")
    eval_dir = directory / "eval"
    eval_dir.mkdir(exist_ok=True)
    records = build_eval_records(items)
    (eval_dir / "items.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in records), encoding="utf-8"
    )
    logger.info("wrote %d items to %s (+eval dataset)", len(items), items_path)
    return items_path, manifest_path


def check_corpus(directory: Path) -> list[str]:
    problems: list[str] = []
    items = _with_split(build_items())
    for name, fresh in (("items.json", items), ("manifest.json", build_manifest(items))):
        path = directory / name
        if not path.exists():
            problems.append(f"{path} is missing")
            continue
        if path.read_text(encoding="utf-8") != _dumps(fresh):
            problems.append(f"{path} differs from a fresh generation — regenerate with --write")
    path = directory / "eval" / "items.jsonl"
    expected = "".join(json.dumps(r, sort_keys=True) + "\n" for r in build_eval_records(items))
    if not path.exists():
        problems.append(f"{path} is missing")
    elif path.read_text(encoding="utf-8") != expected:
        problems.append(f"{path} differs from a fresh generation — regenerate with --write")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true", help="(re)generate the frozen corpus")
    group.add_argument("--check", action="store_true", help="exit 1 if the committed corpus drifted")
    parser.add_argument("--dir", default=str(CORPUS_DIR), help=f"corpus directory (default: {CORPUS_DIR})")
    parser.add_argument("-v", "--verbose", action="store_true", help="DEBUG-level diagnostics")
    args = parser.parse_args(argv)
    configure_logging(args.verbose)

    directory = Path(args.dir)
    if args.write:
        write_corpus(directory)
        return 0
    problems = check_corpus(directory)
    for problem in problems:
        logger.error("%s", problem)
    if not problems:
        logger.info("corpus at %s matches a fresh generation", directory)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
