#!/usr/bin/env python3
"""Validation script for F-035 — shadow-mode merge gate + seed-on-merge.

Deterministic and offline: reads workflow/config files only, runs nothing.

    1. The shadow job runs on every PR (no ENABLE_CALIBRATED_AUTOMERGE guard),
       cannot block (all three decision exit codes succeed), cannot write
       (contents: read, persist-credentials: false, pull-only store sync), and
       surfaces BOTH decisions (agent domain + human/ observability) plus
       store stats in the step summary.
    2. The acting ``gate`` job stays gated and keeps its stricter exit map.
    3. The seed workflow triggers ONLY on push to main (never pull_request —
       fork tokens are read-only and F-032 AC-4 forbids PR-time pushes),
       seeds by GITHUB_SHA under the human/ namespace, and pushes the store
       as its final step.
    4. The committed domain mapping parses, never emits the reserved human/
       namespace, and covers the major subtrees.

Exit codes: 0 all checks passed; 1 one or more failed.
"""

from __future__ import annotations

import logging
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.dirname(_HERE)
for _p in (_HERE, _SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import yaml
from _common import check as _check
from _common import configure_logging, report

logger = logging.getLogger(__name__)

_ROOT = os.path.dirname(_SCRIPTS)
_GATE_WF = os.path.join(".github", "workflows", "calibrated-merge-gate.yml")
_SEED_WF = os.path.join(".github", "workflows", "merge-gate-seed.yml")
_MAPPING = os.path.join("config", "merge-gate-domains.yaml")


def _read(rel_path: str) -> str:
    with open(os.path.join(_ROOT, rel_path), encoding="utf-8") as fh:
        return fh.read()


def _validate_shadow(errors: list[str]) -> None:
    text = _read(_GATE_WF)
    doc = yaml.safe_load(text)
    jobs = doc.get("jobs", {})
    _check("shadow" in jobs, "shadow job exists", errors)
    _check("gate" in jobs, "acting gate job still exists", errors)
    shadow = jobs.get("shadow", {})
    _check(
        "ENABLE_CALIBRATED_AUTOMERGE" not in str(shadow.get("if", "")),
        "shadow job is NOT gated by ENABLE_CALIBRATED_AUTOMERGE (always-on)",
        errors,
    )
    _check(
        "ENABLE_CALIBRATED_AUTOMERGE" in str(jobs.get("gate", {}).get("if", "")),
        "acting gate job stays gated by ENABLE_CALIBRATED_AUTOMERGE",
        errors,
    )
    _check(
        shadow.get("permissions") == {"contents": "read"},
        "shadow job permissions are exactly contents: read",
        errors,
    )
    shadow_text = text[text.index("\n  shadow:") :]
    _check("persist-credentials: false" in shadow_text, "shadow checkout has no creds", errors)
    _check("0 | 10 | 20) exit 0" in shadow_text, "all three decisions succeed in shadow", errors)
    _check("0 | 10) exit 0" in text, "acting gate keeps its stricter exit map", errors)
    _check("store_sync pull" in shadow_text, "shadow pulls the store", errors)
    _check("store_sync push" not in text, "nothing in this workflow pushes the store", errors)
    for needle, why in [
        ("merge_gate_context.py", "context composed from real inputs"),
        ("regression_gate.py", "mech_pass wired to the regression gate"),
        ('.domain = "human/" + .domain', "human/ observability decision emitted"),
        ("GITHUB_STEP_SUMMARY", "decision surfaced in the step summary"),
        ("store_sync stats", "store record counts surfaced"),
    ]:
        _check(needle in shadow_text, f"shadow: {why}", errors)


def _validate_seed(errors: list[str]) -> None:
    text = _read(_SEED_WF)
    doc = yaml.safe_load(text)
    triggers = doc.get("on", doc.get(True, {}))
    _check(
        set(triggers) == {"push"} and triggers["push"].get("branches") == ["main"],
        "seed workflow's ONLY trigger is push to main (F-032 AC-4 verbatim)",
        errors,
    )
    _check(
        doc.get("permissions") == {"contents": "write"},
        "seed permissions are exactly contents: write",
        errors,
    )
    _check("concurrency" not in doc, "no concurrency group (queued-seed drop hazard)", errors)
    for needle, why in [
        ("--human", "seeds under the reserved human/ namespace"),
        ("$GITHUB_SHA", "change_id is the main-push SHA"),
        ("github.event.before", "diff base from the push event"),
        ("--files-from", "NUL-delimited file list (odd-filename safe)"),
        ("agent_core.merge_seed", "seeds via the idempotent merge_seed CLI"),
    ]:
        _check(needle in text, f"seed: {why}", errors)
    order = [text.find("store_sync pull"), text.find("merge_seed"), text.find("store_sync push")]
    _check(
        -1 not in order and order == sorted(order),
        "seed: pull -> seed -> push ordering holds (push is the final store touch)",
        errors,
    )


def _validate_mapping(errors: list[str]) -> None:
    doc = yaml.safe_load(_read(_MAPPING))
    _check(isinstance(doc, dict) and "rules" in doc, "domain mapping parses", errors)
    namespace = str(doc.get("human_namespace", "human/"))
    domains = [str(r.get("domain", "")) for r in doc.get("rules", [])]
    domains.append(str(doc.get("default_domain", "")))
    _check(
        all(d and not d.startswith(namespace) for d in domains),
        "mapping never emits the reserved human/ namespace",
        errors,
    )
    patterns = {str(r.get("pattern", "")) for r in doc.get("rules", [])}
    for expected in ("agent-core/**", "src/**", "scripts/**", ".github/**"):
        _check(expected in patterns, f"mapping covers {expected}", errors)


def validate_f035() -> int:
    configure_logging()
    errors: list[str] = []
    _validate_shadow(errors)
    _validate_seed(errors)
    _validate_mapping(errors)
    return report(logger, "F-035", errors)


def main() -> int:
    return validate_f035()


if __name__ == "__main__":
    sys.exit(main())
