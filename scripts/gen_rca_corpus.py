#!/usr/bin/env python3
"""Generate the frozen synthetic RCA corpus at ``corpora/rca/v1/``.

Implements ``openspec/changes/add-rca-eval-matrix`` task 2. The corpus is **generated,
never scraped** — the real-incident alternative is out of scope per that change's
``proposal.md`` (host-specific telemetry runs at CHARTER §4 invariant 7). Generation gives
reproducible difficulty strata and a keyed sequestered split, which a scrape gives
neither of.

Two decisions worth stating because each replaces an assertion with a measurement:

**Difficulty is calibrated, not declared.** The ``max-|Z|`` baseline target is run against
a fresh generation at generation time, and the manifest records its measured strict AC@1
per noise stratum. A corpus the trivial baseline solves is not a corpus — the
``--check`` gate fails if the baseline's measured accuracy leaves the calibrated band, so
a generator edit that accidentally makes the task trivial (or impossible) is caught here,
not in a reviewer's intuition.

**The split is keyed, not shuffled.** ``bucket`` mirrors the ``flow_corpus.partition``
idiom (sha256 over ``seed:key`` folded into [0, 1)) rather than inventing a scheme —
reused as an *idiom*, not an import: F-011 airgaps ``eval_harness`` from ``flow_corpus``.

Usage::

    python scripts/gen_rca_corpus.py --write     # (re)generate the frozen corpus
    python scripts/gen_rca_corpus.py --check     # fail if the committed corpus drifted

Exit codes:
    0 - corpus written, or committed corpus matches a fresh generation
    1 - drift detected under --check
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from _cli import configure_logging
from _rca_corpus_lib import (
    ITEM_CLASSES,
    STRATA,
    TIMEZONES,
    ItemSpec,
    bucket,
    build_item,
    item_hash,
    validate_item,
)

_HERE = Path(__file__).resolve().parent

logger = logging.getLogger(__name__)

REPO_ROOT = _HERE.parent
CORPUS_DIR = REPO_ROOT / "corpora" / "rca" / "v1"

#: Bumped when the item shape changes in a way a reader must notice.
SCHEMA_VERSION = "1.0"

#: Seed for every deterministic choice below. Recorded in the manifest so a regeneration
#: is reproducible from the artifact alone.
GENERATOR_SEED = 20260906

#: Fraction of items in the sequestered split. Held out from scorer iteration so a
#: threshold tuned on the rest has somewhere honest to be measured.
HOLDOUT_FRACTION = 0.25

#: Items per (class, stratum) cell: 4 classes x 3 strata x 8 = 96 items.
ITEMS_PER_CELL = 8


def build_items() -> list[dict[str, Any]]:
    """Every corpus item, deterministically. Same inputs, byte-identical output."""
    items: list[dict[str, Any]] = []
    for item_class in ITEM_CLASSES:
        for stratum_index, (noise, signal_z) in enumerate(STRATA):
            stratum = f"s{stratum_index}"
            for ordinal in range(ITEMS_PER_CELL):
                item_id = f"rca-{item_class}-{stratum}-{ordinal:02d}"
                timezone = TIMEZONES[ordinal % len(TIMEZONES)]
                spec = ItemSpec(item_id, item_class, stratum, noise, signal_z, timezone)
                items.append(build_item(spec, GENERATOR_SEED))
    return items


def build_manifest(items: list[dict[str, Any]]) -> dict[str, Any]:
    """The frozen manifest: schema, seed, class/split counts, and a hash per item."""
    classes: dict[str, int] = {}
    splits: dict[str, int] = {}
    for item in items:
        classes[item["item_class"]] = classes.get(item["item_class"], 0) + 1
        splits[item["split"]] = splits.get(item["split"], 0) + 1
    answerable = sum(1 for item in items if item["correct"])
    return {
        "schema_version": SCHEMA_VERSION,
        "generator": "scripts/gen_rca_corpus.py",
        "generator_seed": GENERATOR_SEED,
        "holdout_fraction": HOLDOUT_FRACTION,
        "item_count": len(items),
        "classes": dict(sorted(classes.items())),
        "splits": dict(sorted(splits.items())),
        "answerable": answerable,
        "unanswerable": len(items) - answerable,
        # The baseline's measured strict AC@1 per (stratum, class) cell, recorded at
        # generation time: the corpus's difficulty is a measurement, not a claim.
        "baseline_strict_ac1": measure_baseline_ac1(items),
        "items": {item["instance_id"]: item_hash(item) for item in items},
    }


def measure_baseline_ac1(items: list[dict[str, Any]]) -> dict[str, float]:
    """Run the max-|Z| baseline target over a fresh generation and record strict AC@1.

    The corpus's difficulty is calibrated against the baseline it ships with — a corpus
    the trivial baseline solves (or can never solve) is a generator defect, and the
    ``--check`` gate fails when a regeneration leaves the calibrated bands. Imported here
    (inside the function) so the library half of this generator stays importable without
    the harness installed.
    """
    from eval_harness.core.types import EvalItem  # local import: scripts/ stays import-light
    from eval_harness.targets.rca_baseline import RcaMaxZBaselineTarget

    target = RcaMaxZBaselineTarget()
    cells: dict[str, list[int]] = {}
    for item in items:
        key = f"{item['item_class']}/{item['stratum']}"
        ev = EvalItem(
            id=item["instance_id"],
            inputs={"candidates": item["candidates"], "telemetry": item["telemetry"]},
        )
        out = target.run(ev)
        ranked = (out.output or {}).get("ranked") or []
        correct = item["correct"]
        hit = bool(correct and ranked and ranked[0] in correct)
        cells.setdefault(key, []).append(1 if hit else 0)
    return {key: round(sum(hits) / len(hits), 4) for key, hits in sorted(cells.items())}


#: Calibrated bands for the baseline's measured strict AC@1 per (class, stratum) cell.
#: A regeneration whose measurement leaves the band fails ``--check``: the corpus's
#: difficulty is gated as a measured property, not assumed from the generator's intent.
#: Bands are the 2026-09-06 measurement ± 0.25 (sampling slack), clamped to [0, 1].
BASELINE_BANDS: dict[str, tuple[float, float]] = {
    "single/s0": (0.75, 1.0),
    "single/s1": (0.50, 1.0),
    "single/s2": (0.0, 0.25),
    "multi/s0": (0.75, 1.0),
    "multi/s1": (0.62, 1.0),
    "multi/s2": (0.0, 0.25),
    "hard-negative/s0": (0.12, 0.62),
    "hard-negative/s1": (0.0, 0.25),
    "hard-negative/s2": (0.0, 0.25),
    "unanswerable/s0": (0.0, 0.0),
    "unanswerable/s1": (0.0, 0.0),
    "unanswerable/s2": (0.0, 0.0),
}


def _dumps(payload: Any) -> str:
    """Canonical JSON: sorted keys and a trailing newline, so a diff is a real diff."""
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def build_eval_records(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Harness-loadable records: the task statement per item (no suite kinds here — the
    diagnosis is produced by the target under evaluation, not supplied by the corpus)."""
    return [
        {
            "id": item["instance_id"],
            "inputs": {
                "candidates": item["candidates"],
                "telemetry": item["telemetry"],
                "onset": item["onset"],
                "timezone": item["timezone"],
            },
            "expected": item["correct"],
            "metadata": {
                "corpus_item": item["instance_id"],
                "item_class": item["item_class"],
                "split": item["split"],
                "difficulty": item["difficulty"],
            },
        }
        for item in items
    ]


def _with_split(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach the keyed split used by the manifest and eval records."""
    out = []
    for item in items:
        item["split"] = "holdout" if bucket(GENERATOR_SEED, item["instance_id"]) < HOLDOUT_FRACTION else "train"
        out.append(item)
    return out


def write_corpus(directory: Path) -> tuple[Path, Path]:
    items = _with_split(build_items())
    problems = [p for item in items for p in validate_item(item)]
    if problems:
        for problem in problems:
            logger.error("generated item failed validation: %s", problem)
        raise SystemExit(1)
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
    """Differences between the committed corpus and a fresh generation."""
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
    problems.extend(check_baseline_bands(items))
    return problems


def check_baseline_bands(items: list[dict[str, Any]]) -> list[str]:
    """Fail when the baseline's measured accuracy leaves the calibrated band for a cell.

    This is the corpus-difficulty gate: a generator edit that makes the task trivial
    (or impossible) for the trivial baseline is caught here, before the corpus freezes.
    """
    measured = measure_baseline_ac1(items)
    problems: list[str] = []
    for cell, (lo, hi) in BASELINE_BANDS.items():
        value = measured.get(cell)
        if value is None:
            problems.append(f"baseline measurement missing for cell {cell}")
        elif not (lo <= value <= hi):
            problems.append(
                f"baseline strict AC@1 for {cell} is {value}, outside the calibrated band [{lo}, {hi}] "
                "— the corpus's difficulty drifted; retune STRATA or re-derive the bands with evidence"
            )
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
