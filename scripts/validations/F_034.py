#!/usr/bin/env python3
"""Validation script for F-034 — human audit queue + verdict dispatch surface.

Deterministic and offline: reads workflow/script files only, runs nothing.

    1. The scheduled audit workflow is a pure READER: it can select and open
       issues but structurally cannot reach the verdict-writing path (no
       record_audit_verdict, no `audit_sampler ... record`, no store push).
    2. The verdict workflow — the ONLY automated HUMAN_AUDIT writer — is
       human-triggered by construction: workflow_dispatch is its sole trigger,
       with change_id + a correct/incorrect choice input.
    3. Verdict authorization/attribution: environment declared (required
       reviewers attach without code change), auditor allowlist honored,
       actor recorded on both the verdict and the store push, and inputs
       reach shell steps ONLY via env: indirection.
    4. The wrapper enforces idempotency + SHA-shaped change_ids; issue bodies
       offer only the two SYNCED verdict paths (the raw sampler CLI would
       write a local store that never reaches the data branch).

Exit codes: 0 all checks passed; 1 one or more failed.
"""

from __future__ import annotations

import logging
import os
import re
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
_AUDIT_WF = os.path.join(".github", "workflows", "merge-gate-audit.yml")
_VERDICT_WF = os.path.join(".github", "workflows", "merge-gate-verdict.yml")
_ENV_INDIRECTION_RE = re.compile(r"^\s*[A-Z_]+: \$\{\{ inputs\.[a-z_]+ \}\}$")


def _read(rel_path: str) -> str:
    with open(os.path.join(_ROOT, rel_path), encoding="utf-8") as fh:
        return fh.read()


def _validate_audit_reader(errors: list[str]) -> None:
    text = _read(_AUDIT_WF)
    doc = yaml.safe_load(text)
    triggers = set(doc.get("on", doc.get(True, {})))
    _check("schedule" in triggers, "audit selection runs on a schedule", errors)
    _check(
        doc.get("permissions") == {"contents": "read", "issues": "write"},
        "audit workflow permissions are exactly contents: read + issues: write",
        errors,
    )
    _check("record_audit_verdict" not in text, "audit workflow cannot record verdicts", errors)
    _check(
        re.search(r"audit_sampler.*\brecord\b", text) is None,
        "audit workflow cannot reach the sampler's record path",
        errors,
    )
    _check("store_sync push" not in text, "audit workflow never pushes the store", errors)
    for needle, why in [
        ("store_sync pull", "selection reads the synced store"),
        ("audit_issue_sync.py", "issue plan comes from the tested dedupe logic"),
        ("merge-gate-audit", "issues carry the audit label"),
        ("vars.MERGE_GATE_AUDIT_RATE", "sampling rate is a repo variable (I-4)"),
        ("vars.MERGE_GATE_AUDIT_FLOOR", "per-domain floor is a repo variable (I-4)"),
        ("--state all", "dedupe counts closed issues as handled"),
    ]:
        _check(needle in text, f"audit workflow: {why}", errors)


def _validate_verdict_writer(errors: list[str]) -> None:
    text = _read(_VERDICT_WF)
    doc = yaml.safe_load(text)
    triggers = doc.get("on", doc.get(True, {}))
    _check(
        set(triggers) == {"workflow_dispatch"},
        "verdict workflow's ONLY trigger is workflow_dispatch (human-triggered)",
        errors,
    )
    inputs = (triggers.get("workflow_dispatch") or {}).get("inputs", {})
    _check("change_id" in inputs, "dispatch takes a change_id input", errors)
    _check(
        inputs.get("verdict", {}).get("options") == ["correct", "incorrect"],
        "verdict is a correct/incorrect choice input",
        errors,
    )
    job: dict[str, object] = next(iter(doc.get("jobs", {}).values()), {})
    _check(
        job.get("environment") == "merge-gate-verdict",
        "environment declared (required reviewers attach without code change)",
        errors,
    )
    for needle, why in [
        ("MERGE_GATE_AUDITORS", "auditor allowlist honored (fail closed when set)"),
        ("github.actor", "acting human recorded"),
        ("record_audit_verdict.py", "verdicts go through the idempotent wrapper"),
        ('--actor "$ACTOR"', "actor passed via env indirection"),
    ]:
        _check(needle in text, f"verdict workflow: {why}", errors)
    for line in text.splitlines():
        if "${{ inputs." in line:
            _check(
                _ENV_INDIRECTION_RE.match(line) is not None,
                f"inputs only via env: indirection, never inline in run: ({line.strip()})",
                errors,
            )
    order = [
        text.find("store_sync pull"),
        text.find("scripts/record_audit_verdict.py"),
        text.find("store_sync push"),
    ]
    _check(
        -1 not in order and order == sorted(order),
        "verdict: pull -> record -> push ordering holds",
        errors,
    )


def _validate_wrapper_and_bodies(errors: list[str]) -> None:
    wrapper = _read(os.path.join("scripts", "record_audit_verdict.py"))
    for needle, why in [
        ("HUMAN_AUDIT", "already-audited pre-check exists (idempotency outside the TCB)"),
        ("EXIT_UNKNOWN_CHANGE", "unknown change_id fails loudly with a distinct code"),
        ("CHANGE_ID_RE", "change_id must be SHA-shaped"),
    ]:
        _check(needle in wrapper, f"record_audit_verdict.py: {why}", errors)
    renderer = _read(os.path.join("scripts", "audit_issue_sync.py"))
    _check(
        "gh workflow run" in renderer,
        "issue bodies offer the synced gh-workflow-run path",
        errors,
    )
    _check(
        "record --change-id" not in renderer,
        "issue bodies do NOT offer the raw sampler CLI (lost-verdict hazard)",
        errors,
    )


def validate_f034() -> int:
    configure_logging()
    errors: list[str] = []
    _validate_audit_reader(errors)
    _validate_verdict_writer(errors)
    _validate_wrapper_and_bodies(errors)
    return report(logger, "F-034", errors)


def main() -> int:
    return validate_f034()


if __name__ == "__main__":
    sys.exit(main())
