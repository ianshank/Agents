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

#: The negative-control classes, in the order items cycle through them. Named here rather
#: than restated inline so the generator, the manifest census and the tests agree by
#: construction about what classes exist.
CONTROL_CLASSES = ("contradictory", "stale", "mutated")

#: The class of an item that is not a negative control.
ORDINARY_CLASS = "ordinary"

#: Claim keys. A source declares which it asserts (``supports``) and which it denies
#: (``refutes``); a generated requirement declares the one it asserts. Structured rather
#: than inferred from prose so the grounding check is deterministic and offline — and so a
#: contradiction is *derived* from two sources disagreeing rather than declared by a flag
#: that would mark the item as a negative control (task 2.2).
CLAIM_PERSISTENCE = "persistence"
CLAIM_AUTH_REQUIRED = "auth_required"
CLAIM_QUOTA = "quota"

#: Asserted by the stand-in, supported by no source in any item. The spec's
#: unsupported-constraint scenario: evidence mentions no performance target, the generated
#: set asserts a latency budget.
CLAIM_LATENCY_BUDGET = "latency_budget"

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


def _gold_acs(domain: str, count: int) -> list[dict[str, str]]:
    """The declared gold acceptance criteria for one epic.

    Templated rather than sampled: the corpus is a fixture, and a seeded RNG here would
    only look like variation while producing one fixed sequence anyway.
    """
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
        domain = _DOMAINS[ordinal % len(_DOMAINS)]
        epic_id = f"req-{ordinal:02d}"
        gold = _gold_acs(domain, 3 + ordinal % 3)

        # Every item declares two evidence sources; the control class decides what they
        # contain. Source bytes live in the corpus so the offline store can serve them.
        src_a = f"src-{epic_id}-a"
        src_b = f"src-{epic_id}-b"
        # src_a is the governance source (persistence + authentication); src_b is the
        # quota source. Splitting the claims across the two sources is what lets a control
        # put them in genuine conflict: a contradictory src_b denies a claim src_a asserts.
        base_a = f"The {domain} service persists submissions and requires authentication for all actions."
        supports_a = [CLAIM_PERSISTENCE, CLAIM_AUTH_REQUIRED]
        base_b = f"The {domain} service enforces a per-tenant quota."
        supports_b, refutes_b = [CLAIM_QUOTA], []

        control = ORDINARY_CLASS
        if ordinal < control_count:
            control = CONTROL_CLASSES[ordinal % len(CONTROL_CLASSES)]
        if control == "contradictory":
            # Denies src_a's authentication requirement outright. Each class gets a
            # distinct observable signature: contradictory shows up as a requirement
            # citing a claim another recorded source refutes; stale as a claim no
            # surviving source supports; mutated as post-capture provenance drift.
            base_b = f"The {domain} service allows anonymous actions without authentication."
            supports_b, refutes_b = [], [CLAIM_AUTH_REQUIRED]
        elif control == "stale":
            base_b = f"DEPRECATED (rev 1): the {domain} service enforces no quota."
            supports_b, refutes_b = [], [CLAIM_QUOTA]
        # The "mutated" control leaves the evidence bytes alone here on purpose: what it
        # mutates is what the *drifted* store later serves, so a re-fetch through that
        # store diverges from the hash recorded against these bytes.

        evidence = {
            src_a: base_a,
            src_b: base_b,
        }
        sources = [
            {
                "source_type": "drive_doc",
                "source_id": src_a,
                "reference": {"kind": "revision_export_link", "revision_id": f"rev-{epic_id}-a", "mime": "text/plain"},
                "supports": supports_a,
                "refutes": [],
            },
            {
                "source_type": "drive_doc",
                "source_id": src_b,
                "reference": {"kind": "revision_export_link", "revision_id": f"rev-{epic_id}-b", "mime": "text/plain"},
                "supports": supports_b,
                "refutes": refutes_b,
            },
        ]
        # What a post-capture edit would serve on a re-fetch. Identical to the captured
        # bytes except for the mutated control, whose src_b drifted.
        drifted_bytes = dict(evidence)
        recorded_hashes = {sid: hashlib.sha256(data.encode()).hexdigest() for sid, data in evidence.items()}
        if control == "mutated":
            drifted_bytes[src_b] = base_b + " (edited after capture)"

        items.append(
            {
                "epic_id": epic_id,
                "domain": domain,
                "title": f"{domain.title()} epic {ordinal}",
                "statement": f"As a {domain} owner I need the {domain} workflow hardened.",
                "gold_ac": gold,
                "evidence_sources": sources,
                "evidence_bytes": evidence,
                "drifted_bytes": drifted_bytes,
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


#: Generation temperature the scripted stand-in reports. A diversity score without one is
#: uninterpretable by contract, so the stand-in has to declare the value it "ran at".
STANDIN_TEMPERATURE = 0.7

#: Every Nth epic's stand-in drops its last gold criterion, so recall varies across the
#: corpus instead of being a flat 1.0 that would prove nothing about the scorer.
STANDIN_DROP_EVERY = 3

#: Every Nth epic's stand-in cites a source the wrapper never recorded, so the
#: hallucination rate is exercised rather than constantly zero.
STANDIN_UNSUPPORTED_EVERY = 5

#: Every Nth epic's stand-in asserts a latency budget against a source that *is* recorded
#: but supports no such claim. Distinct from the modulus above on purpose: one exercises
#: the citation check, the other the support check, and a corpus that only ever failed
#: the first would leave the second unproven.
STANDIN_UNGROUNDED_EVERY = 4

#: The uncited source id the unsupported requirement points at. Deliberately absent from
#: every item's ``evidence_sources``, so no run can record it.
STANDIN_UNRECORDED_SOURCE = "src-not-retrieved"


def build_standin(item: dict[str, Any], ordinal: int) -> dict[str, Any]:
    """A scripted generator output for one epic — the artifact the scorers grade.

    **This is a stand-in, not a measurement.** It is derived from the gold set on purpose:
    its job is to make the shipped journey exercise all four scorers offline with no model
    call. Scores it produces describe the stand-in, never a real generator. A real run
    points ``inner_spec`` at the system under test and these fields go unused.

    Scripted to be imperfect and to vary, because a demo that scores a flat 1.0 (or a flat
    0.0) cannot distinguish a working scorer from a broken one.
    """
    gold = item["gold_ac"]
    domain = item["domain"]
    covered = gold[:-1] if ordinal % STANDIN_DROP_EVERY == 0 and len(gold) > 1 else gold
    governance_source, quota_source = (s["source_id"] for s in item["evidence_sources"])
    first_ac = gold[0]["id"]
    declared_test = item["declared_tests"][:1]

    def requirement(text: str, claim: str, covers: list[str], links: list[str], tests: list[str]) -> dict[str, Any]:
        return {
            "id": f"{item['epic_id']}-r{len(requirements)}",
            "text": text,
            "claim": claim,
            "covers": covers,
            "evidence_links": links,
            "test_links": tests,
        }

    requirements: list[dict[str, Any]] = []
    for ac in covered:
        requirements.append(
            requirement(
                f"The {domain} service SHALL ensure {ac['text']}.",
                CLAIM_PERSISTENCE,
                [ac["id"]],
                [governance_source],
                declared_test,
            )
        )
    # Emitted for *every* item, so the field shape cannot mark a control. What differs is
    # the outcome: the authentication claim is cleanly supported on an ordinary item and
    # contradicted on a contradictory one, and the quota claim loses its support on a
    # stale one. The control class is a property of the evidence, never of the record.
    requirements.append(
        requirement(
            f"The {domain} service SHALL require authentication for every action.",
            CLAIM_AUTH_REQUIRED,
            [first_ac],
            [governance_source],
            declared_test,
        )
    )
    requirements.append(
        requirement(
            f"The {domain} service SHALL enforce the per-tenant quota.",
            CLAIM_QUOTA,
            [first_ac],
            [quota_source],
            declared_test,
        )
    )
    if ordinal % STANDIN_UNSUPPORTED_EVERY == 0:
        requirements.append(
            requirement(
                f"The {domain} service SHALL respond within a fixed latency budget.",
                CLAIM_LATENCY_BUDGET,
                [],
                [STANDIN_UNRECORDED_SOURCE],
                [],
            )
        )
    if ordinal % STANDIN_UNGROUNDED_EVERY == 0:
        requirements.append(
            requirement(
                f"The {domain} service SHALL complete every request within a fixed latency budget.",
                CLAIM_LATENCY_BUDGET,
                [first_ac],
                [governance_source],
                declared_test,
            )
        )
    return {"requirements": requirements, "generation_temperature": STANDIN_TEMPERATURE}


def build_eval_records(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Harness-loadable records: the epic, its gold set, and its declared evidence.

    ``evidence_bytes``/``drifted_bytes``/``recorded_hashes`` stay OUT of the record — they
    are corpus-internal ground truth the target must not see (the wrapper fetches through
    the store, and the verification pass compares against the recorded hashes).

    **So does ``control``.** Task 2.2 requires that no field the target sees distinguishes
    a negative control from an ordinary item, and ``EvalItem.metadata`` is handed to the
    target along with everything else. The class stays in ``items.json``, which the harness
    never loads; an analysis joins it back on ``corpus_item``. The split stays out for the
    same reason it need not be here: it is the file the record lands in, not a label.

    ``generated`` is the scripted stand-in (see :func:`build_standin`), which the shipped
    config surfaces with ``echo``'s ``output_key``. A real evaluation replaces the inner
    target and ignores this field.
    """
    return [
        {
            "id": item["epic_id"],
            "inputs": {
                "epic": item["statement"],
                "title": item["title"],
                "evidence_sources": item["evidence_sources"],
                "declared_tests": item["declared_tests"],
                "generated": build_standin(item, ordinal),
            },
            "expected": [ac["id"] for ac in item["gold_ac"]],
            "metadata": {"corpus_item": item["epic_id"]},
        }
        for ordinal, item in enumerate(items)
    ]


def build_store(items: list[dict[str, Any]], *, key: str = "evidence_bytes") -> dict[str, str]:
    """An offline evidence store: ``source_id -> served bytes``, drawn from *key*.

    Two stores ship, and the pair is what makes the mutated control mean anything. The
    capture store (``evidence_bytes``) serves the bytes the recorded hashes cover, so an
    ordinary run verifies clean. The drift store (``drifted_bytes``) serves what a
    re-fetch would return after a post-capture edit, so re-verifying the *same* records
    against it fails for exactly the mutated controls. One store alone can only record a
    hash; it cannot demonstrate that verification detects drift (task 2.3).
    """
    store: dict[str, str] = {}
    for item in items:
        for source_id, content in item[key].items():
            store[str(source_id)] = str(content)
    return store


def _with_split(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Copies carrying a keyed ``split``. Copies, not in-place edits, so a caller that
    reuses its own list does not find it silently rewritten."""
    return [
        {**item, "split": ("holdout" if _bucket(GENERATOR_SEED, item["epic_id"]) < HOLDOUT_FRACTION else "train")}
        for item in items
    ]


def _jsonl(records: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(r, sort_keys=True) + "\n" for r in records)


def split_records(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Eval records partitioned into the train and holdout splits.

    Two files rather than one file plus a metadata label: a label is only a sequestered
    split if something enforces it, and nothing in a dataset config filters on metadata.
    The shipped config names the train artifact, so iterating on scorers cannot see the
    holdout by default (task 2.5). Records are built over the *whole* corpus first, so an
    item's scripted stand-in does not change with the split it lands in.
    """
    partitioned: dict[str, list[dict[str, Any]]] = {"train": [], "holdout": []}
    for record, item in zip(build_eval_records(items), items, strict=True):
        partitioned[str(item["split"])].append(record)
    return partitioned


def write_corpus(directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "eval").mkdir(exist_ok=True)
    for relative, text in generated_artifacts().items():
        (directory / relative).write_text(text, encoding="utf-8")
    items_path, manifest_path = directory / "items.json", directory / "manifest.json"
    logger.info("wrote %d artifacts under %s", len(generated_artifacts()), directory)
    return items_path, manifest_path


def generated_artifacts() -> dict[str, str]:
    """Every file ``--write`` emits, mapped to its expected text.

    One derivation shared by the writer's expectations and the checker, so an artifact
    added to the corpus cannot be written without also being freshness-gated.
    """
    items = _with_split(build_items())
    splits = split_records(items)
    return {
        "items.json": _dumps(items),
        "manifest.json": _dumps(build_manifest(items)),
        "eval/train.jsonl": _jsonl(splits["train"]),
        "eval/holdout.jsonl": _jsonl(splits["holdout"]),
        "eval/store.json": _dumps(build_store(items)),
        "eval/store.drifted.json": _dumps(build_store(items, key="drifted_bytes")),
    }


def check_corpus(directory: Path) -> list[str]:
    problems: list[str] = []
    for relative, expected in generated_artifacts().items():
        path = directory / relative
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
