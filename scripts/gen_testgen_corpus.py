#!/usr/bin/env python3
"""Generate the frozen test-generation corpus at ``corpora/testgen/v1/``.

Implements ``openspec/changes/add-testgen-eval-matrix`` task 1. The corpus is
**generated, never scraped** — see that change's ``proposal.md`` "Why the corpus is
synthetic": a corpus of real internal focal methods would be committed source from
internal systems, which runs at CHARTER §4 invariant 7 and would need a §3 Ratified
Amendment. Generation also gives reproducible difficulty strata and unlimited held-out
material, which a scrape gives neither of.

Three decisions here are worth stating, because each replaces an assertion with a
measurement:

**Equivalence is decided, not declared.** A mutant is marked equivalent iff it agrees
with the reference on every point of a bounded input grid. The alternative — a generator
that labels a mutation "equivalent" because its author believed the operator was
semantics-preserving — would put an unchecked claim into the denominator of every
mutation score computed from this corpus.

**Obligations carry a witness mutant.** An obligation is a behavioural partition of the
input grid, paired with a mutant that provably breaks that partition and nothing weaker.
"Covered" then means "the suite killed the witness", which is decidable by execution.
Deriving obligations from the generated tests instead would be circular — a suite would
define its own target and always score highly — which the spec delta forbids outright.

**The split is keyed, not shuffled.** ``_bucket`` mirrors ``flow-corpus``'s
``flow_corpus/partition.py:22`` idiom (sha256 over ``seed:key``, scaled into ``[0, 1)``)
rather than inventing a scheme. Reused as an *idiom*, not an import: F-011 airgaps
``eval_harness`` from ``flow_corpus``, and this corpus is loaded by the harness.

Usage::

    python scripts/gen_testgen_corpus.py --write     # (re)generate the frozen corpus
    python scripts/gen_testgen_corpus.py --check     # fail if the committed corpus drifted

Exit codes:
    0 - corpus written, or committed corpus matches a fresh generation
    1 - drift detected under --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from pathlib import Path
from typing import Any

from _cli import configure_logging
from _testgen_corpus_lib import (
    _OPERATORS,
    _TEMPLATES,
    _THRESHOLDS,
    GRID,
    SUITE_KINDS,
    _behaviour,
    _bucket,
    _build_mutants,
    _build_obligations,
    _build_suites,
    weak_is_strictly_weaker,
)

_HERE = Path(__file__).resolve().parent

logger = logging.getLogger(__name__)

REPO_ROOT = _HERE.parent
CORPUS_DIR = REPO_ROOT / "corpora" / "testgen" / "v1"

#: Bumped when the item shape changes in a way a reader must notice.
SCHEMA_VERSION = "1.0"

#: Seed for every deterministic choice below. Recorded in the manifest so a regeneration
#: is reproducible from the artifact alone.
GENERATOR_SEED = 20260905

#: Fraction of items in the sequestered split. Held out from scorer iteration so a
#: threshold tuned on the rest has somewhere honest to be measured.
HOLDOUT_FRACTION = 0.25


#: How many focal methods each control-flow stratum contributes. 12 x 5 = 60 items, the
#: size ``tasks.md`` 1.3 fixes.
ITEMS_PER_STRATUM = 12


# --------------------------------------------------------------------------- generation


def build_items() -> list[dict[str, Any]]:
    """Every corpus item, deterministically. Same inputs, byte-identical output."""
    items: list[dict[str, Any]] = []
    for stratum, template in _TEMPLATES.items():
        for ordinal in range(ITEMS_PER_STRATUM):
            item_id = f"tg-{stratum}-{ordinal:02d}"
            name = f"focal_{stratum}_{ordinal:02d}"
            source = template.format(
                name=name,
                t=_THRESHOLDS[stratum][ordinal % len(_THRESHOLDS[stratum])],
                op=_OPERATORS[ordinal % len(_OPERATORS)],
            ).strip()
            reference = _behaviour(source, name)
            mutants = _build_mutants(source, name, reference)
            obligations = _build_obligations(reference, mutants)
            non_equivalent = [m for m in mutants if not m.equivalent]
            if not non_equivalent or not obligations:
                # An item nothing can distinguish teaches a suite nothing and would drag
                # every denominator toward zero. Skipped loudly rather than shipped.
                logger.warning(
                    "skipping %s: %d non-equivalent mutants, %d obligations",
                    item_id,
                    len(non_equivalent),
                    len(obligations),
                )
                continue
            items.append(
                {
                    "id": item_id,
                    "stratum": stratum,
                    "focal_name": name,
                    "reference": source,
                    "mutants": [
                        {
                            "id": m.id,
                            "kind": m.kind,
                            "equivalent": m.equivalent,
                            "source": m.source,
                            # Grid indices where this mutant diverges. The target needs
                            # them to decide "covered" -- whether the suite actually drove
                            # an input at which the mutant differs -- rather than guessing
                            # the normalized denominator.
                            "differs_at": list(m.differs_at),
                        }
                        for m in mutants
                    ],
                    "obligations": obligations,
                    "suites": _build_suites(name, reference, mutants),
                    "split": "holdout" if _bucket(GENERATOR_SEED, item_id) < HOLDOUT_FRACTION else "train",
                }
            )
    return items


def build_manifest(items: list[dict[str, Any]]) -> dict[str, Any]:
    """The frozen manifest: schema, seed, strata counts, and a hash per item."""
    strata: dict[str, int] = {}
    splits: dict[str, int] = {}
    for item in items:
        strata[item["stratum"]] = strata.get(item["stratum"], 0) + 1
        splits[item["split"]] = splits.get(item["split"], 0) + 1
    return {
        "schema_version": SCHEMA_VERSION,
        "generator": "scripts/gen_testgen_corpus.py",
        "generator_seed": GENERATOR_SEED,
        "holdout_fraction": HOLDOUT_FRACTION,
        "grid_size": len(GRID),
        "item_count": len(items),
        "strata": dict(sorted(strata.items())),
        "splits": dict(sorted(splits.items())),
        # How much of the corpus can actually calibrate the mutation axis: the number of
        # items whose known-BAD `weak` suite kills strictly fewer mutants than the
        # known-GOOD `thorough` one. Measured rather than claimed, because it silently was
        # not all of them — `weak` was built from the single most discriminating assertion
        # available, so for 32 of these 60 items it came out byte-identical to `thorough`
        # apart from the test function's name, and every check on those suites compared
        # text rather than running them.
        "weak_strictly_weaker_items": sum(1 for item in items if weak_is_strictly_weaker(item)),
        # The grid itself, so a consumer can map a mutant's `differs_at` indices back to
        # inputs without re-deriving GRID from this generator.
        "grid": [list(point) for point in GRID],
        "items": {item["id"]: _item_hash(item) for item in items},
    }


def _item_hash(item: dict[str, Any]) -> str:
    """A content hash over the item, so a hand-edited corpus fails --check."""
    return hashlib.sha256(_dumps(item).encode()).hexdigest()


def _dumps(payload: Any) -> str:
    """Canonical JSON: sorted keys and a trailing newline, so a diff is a real diff."""
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def build_eval_records(items: list[dict[str, Any]], suite_kind: str) -> list[dict[str, Any]]:
    """Harness-loadable records pairing each focal method with one reference suite.

    Emitted per suite kind so the shipped `jsonl` dataset can load a corpus slice with no
    bespoke dataset class: the corpus states the task, and these four files state four
    known answers to it. `thorough` and `weak` are the "known-good"/"known-bad" pair the
    change's task 6.4 dry-runs; `broken` and `false_alarm` pin the two failure shapes the
    spec insists stay distinguishable from a merely low score.
    """
    grid = [list(point) for point in GRID]
    return [
        {
            "id": f"{item['id']}-{suite_kind}",
            "inputs": {
                "focal_name": item["focal_name"],
                "reference": item["reference"],
                "suite": item["suites"][suite_kind],
                "mutants": item["mutants"],
                "obligations": item["obligations"],
                "grid": grid,
            },
            "metadata": {
                "corpus_item": item["id"],
                "stratum": item["stratum"],
                "split": item["split"],
                "suite_kind": suite_kind,
            },
        }
        for item in items
    ]


def write_corpus(directory: Path) -> tuple[Path, Path]:
    items = build_items()
    directory.mkdir(parents=True, exist_ok=True)
    items_path = directory / "items.json"
    manifest_path = directory / "manifest.json"
    items_path.write_text(_dumps(items), encoding="utf-8")
    manifest_path.write_text(_dumps(build_manifest(items)), encoding="utf-8")
    eval_dir = directory / "eval"
    eval_dir.mkdir(exist_ok=True)
    for kind in SUITE_KINDS:
        records = build_eval_records(items, kind)
        (eval_dir / f"{kind}.jsonl").write_text(
            "".join(json.dumps(r, sort_keys=True) + "\n" for r in records), encoding="utf-8"
        )
    logger.info("wrote %d items to %s (+%d eval datasets)", len(items), items_path, len(SUITE_KINDS))
    return items_path, manifest_path


def check_corpus(directory: Path) -> list[str]:
    """Differences between the committed corpus and a fresh generation."""
    problems: list[str] = []
    items = build_items()
    for name, fresh in (("items.json", items), ("manifest.json", build_manifest(items))):
        path = directory / name
        if not path.exists():
            problems.append(f"{path} is missing")
            continue
        if path.read_text(encoding="utf-8") != _dumps(fresh):
            problems.append(f"{path} differs from a fresh generation — regenerate with --write")
    for kind in SUITE_KINDS:
        path = directory / "eval" / f"{kind}.jsonl"
        expected = "".join(json.dumps(r, sort_keys=True) + "\n" for r in build_eval_records(items, kind))
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
