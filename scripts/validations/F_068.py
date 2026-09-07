#!/usr/bin/env python3
"""Validation script for F-068 — requirements-generation evaluation (synthetic scope).

Implements ``openspec/changes/add-requirements-gen-eval-matrix`` task 6.1. Every check
below is established by RUNNING the thing it describes (the F-063 lesson): evidence
records are built, the verification pass re-fetches, and the scorers grade real outputs.

Checks:
1.  An unpinnable source carries NO content hash — a reader cannot mistake a
    churn-prone hash for a verified one (spec: "Only obtainable metadata is recorded").
2.  A mutated source is detected by the provenance verification pass, reported as a
    provenance failure distinct from a scoring failure.
3.  A diversity score without a generation temperature is reported uninterpretable,
    never compared to the floor.
4.  Recall is the covered fraction of the DECLARED gold set; an unsupported constraint
    is flagged against the recorded evidence; an asserted (prose) link is not a link.
5.  The committed corpus regenerates byte-identically, carries the negative-control
    classes, and holds out a sequestered split.
6.  Every shipped gate rule for this capability is advisory (report_only).

Exit codes:
    0 - all checks passed
    1 - one or more checks failed
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from _common import check as _check
from _common import configure_logging, report

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))
sys.path.insert(0, PROJECT_ROOT)

#: The four scorers this feature registers.
_SCORERS = (
    "req_ac_recall",
    "req_scope_hallucination",
    "req_traceability_closure",
    "req_semantic_diversity",
)

_CONFIG = os.path.join(PROJECT_ROOT, "config", "requirements_eval.yaml")
_CORPUS = os.path.join(PROJECT_ROOT, "corpora", "requirements", "v1")


def _check_unpinnable_records_carry_no_hash(errors: list[str]) -> None:
    from eval_harness.targets.provenance import build_evidence_record

    unpinnable = build_evidence_record(
        "context7", "lib-1", {"kind": "context7_blob", "query": "auth"}, b"blob", retrieved_at="t"
    )
    _check(
        unpinnable.get("pinnable") is False and "content_sha256" not in unpinnable,
        "an unpinnable source carries no content hash (omitting the field is the point)",
        errors,
    )
    pinnable = build_evidence_record(
        "drive_doc", "doc-1", {"kind": "revision_export_link", "revision_id": "r1"}, b"bytes", retrieved_at="t"
    )
    _check(
        pinnable.get("pinnable") is True and bool(pinnable.get("content_sha256")),
        "a revision-scoped reference carries a hash over the bytes it returned",
        errors,
    )


def _check_mutated_source_is_detected(errors: list[str]) -> None:
    from eval_harness.targets.provenance import MappingEvidenceStore, build_evidence_record, verify_provenance

    record = build_evidence_record(
        "drive_doc", "doc-1", {"kind": "revision_export_link", "revision_id": "r1"}, b"original", retrieved_at="t"
    )
    mutated = MappingEvidenceStore(contents={"doc-1": b"mutated"})
    failures = verify_provenance([record], mutated)
    _check(
        len(failures) == 1 and "drifted" in failures[0],
        "a mutated source is detected by the provenance check (a provenance failure, not a score)",
        errors,
    )
    stable = MappingEvidenceStore(contents={"doc-1": b"original"})
    _check(verify_provenance([record], stable) == [], "stable content verifies clean", errors)


def _check_corpus_drift_is_detected_end_to_end(errors: list[str]) -> None:
    """Task 2.3's actual claim: not that the corpus *holds* mutated bytes, but that the
    verification pass *detects* them. Proven over the corpus's own artifacts, with the
    records produced the way a run produces them, because a hand-built record and a
    hand-built store can demonstrate the mechanism while the shipped corpus exercises
    none of it — which is exactly what had happened."""
    from eval_harness.core.types import REQUIREMENTS_EVIDENCE_KEY, EvalItem
    from eval_harness.targets.provenance import MappingEvidenceStore, ProvenanceRecorderTarget, verify_provenance
    from gen_requirements_corpus import build_eval_records, build_items, build_store

    items = build_items()
    capture = build_store(items)
    drifted = MappingEvidenceStore({k: v.encode("utf-8") for k, v in build_store(items, key="drifted_bytes").items()})
    target = ProvenanceRecorderTarget(
        inner_spec={"type": "echo", "params": {"output_key": "generated"}}, store_contents=capture
    )
    clean, drifting = [], []
    for record, item in zip(build_eval_records(items), items, strict=True):
        output = target.run(EvalItem(id=record["id"], inputs=record["inputs"], expected=record["expected"]))
        records = output.metadata[REQUIREMENTS_EVIDENCE_KEY]
        if verify_provenance(records, MappingEvidenceStore({k: v.encode("utf-8") for k, v in capture.items()})):
            clean.append(item["epic_id"])
        if verify_provenance(records, drifted):
            drifting.append(item["control"])
    _check(not clean, f"every item verifies clean against the bytes it captured (drifted: {clean[:2]})", errors)
    expected = [i["control"] for i in items if i["control"] == "mutated"]
    _check(
        sorted(drifting) == sorted(expected) and bool(expected),
        f"re-verifying against the drift store fails for exactly the mutated controls (observed {sorted(set(drifting))})",
        errors,
    )


def _score(name: str, output: Any, item: Any) -> Any:
    from eval_harness.core.types import EvalItem, RunContext, TargetOutput
    from eval_harness.plugins import SCORERS, bootstrap

    bootstrap()
    eval_item = item if isinstance(item, EvalItem) else EvalItem(id="v", inputs={})
    target_out = output if isinstance(output, TargetOutput) else TargetOutput(output=output)
    return SCORERS.create(name, {}).score(eval_item, target_out, RunContext(config=None))


def _check_scorer_semantics(errors: list[str]) -> None:
    from eval_harness.core.types import EvalItem, TargetOutput

    gold = [{"id": f"ac-{i}", "text": "t"} for i in range(8)]
    item = EvalItem(id="v", inputs={}, metadata={"gold_ac": gold})
    six_of_eight = TargetOutput(output={"requirements": [{"id": "r1", "covers": [f"ac-{i}" for i in range(6)]}]})
    recall = _score("req_ac_recall", six_of_eight, item)
    _check(
        getattr(recall, "value", None) == 0.75,
        f"recall is the covered fraction of the declared set (observed {getattr(recall, 'value', None)})",
        errors,
    )

    no_temp = TargetOutput(output={"requirements": [{"text": "alpha beta"}, {"text": "gamma delta"}]})
    diversity = _score("req_semantic_diversity", no_temp, item)
    _check(
        getattr(diversity, "passed", True) is None,
        "a diversity score without a temperature is uninterpretable, not compared to the floor",
        errors,
    )

    from eval_harness.core.types import REQUIREMENTS_EVIDENCE_KEY

    prose = TargetOutput(
        output={"requirements": [{"id": "r1", "covers": ["ac-1"], "test_links": ["undeclared"], "text": "covered"}]},
        metadata={REQUIREMENTS_EVIDENCE_KEY: [{"source_id": "doc-1", "pinnable": True}]},
    )
    with_tests = EvalItem(id="v", inputs={"declared_tests": ["test_real"]}, metadata={"gold_ac": gold})
    closure = _score("req_traceability_closure", prose, with_tests)
    _check(
        getattr(closure, "passed", True) is False,
        "an asserted link to an undeclared test breaks the chain (prose is not a link)",
        errors,
    )

    undeclared_ac = TargetOutput(
        output={"requirements": [{"id": "r1", "covers": ["ac-invented"], "test_links": ["test_real"]}]},
        metadata={REQUIREMENTS_EVIDENCE_KEY: [{"source_id": "doc-1", "pinnable": True}]},
    )
    invented = _score("req_traceability_closure", undeclared_ac, with_tests)
    _check(
        getattr(invented, "passed", True) is False,
        "a covers link to a criterion outside the declared gold set does not close the chain",
        errors,
    )

    # The spec's unsupported-constraint scenario, against a source that IS recorded: only
    # reading what the source claims can catch it, which a citation check cannot.
    latency = TargetOutput(
        output={"requirements": [{"id": "r1", "claim": "latency_budget", "evidence_links": ["doc-1"]}]},
        metadata={REQUIREMENTS_EVIDENCE_KEY: [{"source_id": "doc-1", "pinnable": True}]},
    )
    claiming = EvalItem(
        id="v",
        inputs={"evidence_sources": [{"source_id": "doc-1", "supports": ["persistence"], "refutes": []}]},
        metadata={"gold_ac": gold},
    )
    unsupported = _score("req_scope_hallucination", latency, claiming)
    _check(
        getattr(unsupported, "value", None) == 1.0,
        "an assertion no cited source supports is flagged even though the citation resolves",
        errors,
    )

    disputed = EvalItem(
        id="v",
        inputs={
            "evidence_sources": [
                {"source_id": "doc-1", "supports": ["auth_required"], "refutes": []},
                {"source_id": "doc-2", "supports": [], "refutes": ["auth_required"]},
            ]
        },
        metadata={"gold_ac": gold},
    )
    picked = TargetOutput(
        output={"requirements": [{"id": "r1", "claim": "auth_required", "evidence_links": ["doc-1"]}]},
        metadata={
            REQUIREMENTS_EVIDENCE_KEY: [
                {"source_id": "doc-1", "pinnable": True},
                {"source_id": "doc-2", "pinnable": True},
            ]
        },
    )
    contradiction = _score("req_scope_hallucination", picked, disputed)
    _check(
        getattr(contradiction, "passed", True) is False
        and contradiction.metadata["contradiction_citations"] == ["r1"],
        "a requirement asserting one side of a contradiction is reported, not scored as cleanly supported",
        errors,
    )


def _check_corpus(errors: list[str]) -> None:
    import json

    from gen_requirements_corpus import check_corpus

    problems = check_corpus(__import__("pathlib").Path(_CORPUS))
    _check(not problems, f"the committed corpus regenerates byte-identically (problems: {problems[:2]})", errors)

    with open(os.path.join(_CORPUS, "manifest.json"), encoding="utf-8") as handle:
        manifest = json.load(handle)
    classes = manifest.get("classes", {})
    _check(
        {"contradictory", "stale", "mutated"} <= set(classes),
        f"the corpus carries the negative-control classes (observed {sorted(classes)})",
        errors,
    )
    splits = manifest.get("splits", {})
    _check(
        0 < splits.get("holdout", 0) < splits.get("train", 0),
        "a sequestered holdout split exists and is a minority",
        errors,
    )

    with open(_CONFIG, encoding="utf-8") as handle:
        dataset_path = str(((yaml.safe_load(handle).get("dataset") or {}).get("params") or {}).get("path", ""))
    _check(
        dataset_path.endswith("train.jsonl") and os.path.exists(os.path.join(_CORPUS, "eval", "holdout.jsonl")),
        f"the shipped config reads the train split, leaving the holdout sequestered (reads {dataset_path!r})",
        errors,
    )

    from gen_requirements_corpus import build_eval_records, build_items

    leaked = [r["id"] for r in build_eval_records(build_items()) if "control" in r.get("metadata", {})]
    _check(
        not leaked,
        f"no harness-loaded record carries its control class, which the target would see (leaked: {leaked[:2]})",
        errors,
    )


def _check_every_shipped_rule_is_advisory(errors: list[str]) -> None:
    with open(_CONFIG, encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    rules = (config.get("gate") or {}).get("rules") or []
    ours = [rule for rule in rules if rule.get("score") in _SCORERS]
    _check(len(ours) == len(_SCORERS), f"the shipped config gates all four scorers (found {len(ours)})", errors)
    _check(
        all(rule.get("report_only") is True for rule in ours),
        "every shipped gate rule for this capability is advisory (a sub-floor diversity "
        "score escalates through the advisory channel rather than failing the run)",
        errors,
    )


def main() -> int:
    configure_logging()
    errors: list[str] = []
    _check_unpinnable_records_carry_no_hash(errors)
    _check_mutated_source_is_detected(errors)
    _check_corpus_drift_is_detected_end_to_end(errors)
    _check_scorer_semantics(errors)
    _check_corpus(errors)
    _check_every_shipped_rule_is_advisory(errors)
    return report(logger, "F-068", errors)


if __name__ == "__main__":
    sys.exit(main())
