#!/usr/bin/env python3
"""Validation script for F-048 — credential scrub + fail-closed secret-scan gate.

Asserts the three parts of the hygiene gate stay in place:
    1. ``.gitleaks.toml`` exists, extends the default ruleset, and stores no secret
       literal of its own (a config that embedded the scrubbed key would reintroduce the
       very string the working-tree gate exists to catch).
    2. ``secret-scan.yml`` wires gitleaks with the documented asymmetry: the working-tree
       scan (``--no-git``) is FAIL-CLOSED, while the history scan is report-only
       (``--exit-code 0``) because the known finding is deliberately not rewritten out of
       history (ADR 0027). It also runs on EVERY pull request: a ``paths:`` filter is
       evaluated per workflow, so while this job lived in ``quality-gates.yml`` a
       docs-only pull request skipped it while a stub reported its context green.
    3. No Langfuse key literal survives in the scrubbed files. The check is written as a
       prefix scan over all tracked markdown rather than a fixed list, so a key
       reintroduced in a NEW file fails too.

The prefixes below are the vendor's public key-format markers (``sk-lf-`` / ``pk-lf-``),
not secrets; matching bare prefixes would flag this file and every doc describing the
incident, so a literal only counts when followed by UUID-shaped key material.

Deterministic and offline: reads files, runs nothing.

Exit codes:
    0 - all checks passed
    1 - one or more checks failed
"""

from __future__ import annotations

import logging
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_SCRIPTS)
for _p in (_HERE, _SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _common import check as _check
from _common import configure_logging, report

logger = logging.getLogger(__name__)

_CONFIG = ".gitleaks.toml"
#: The scan's own workflow. It used to be a job inside ``quality-gates.yml``, whose
#: ``paths:`` filter is evaluated per WORKFLOW — so a pull request touching only docs,
#: demos, skills or a corpus never started it, and the companion stub in
#: ``required-check-stubs.yml`` reported the context green anyway. A credential can be
#: committed in any file, so the scan now runs unfiltered from a file of its own, and this
#: validator follows it there rather than continuing to assert about its old home.
_WORKFLOW = os.path.join(".github", "workflows", "secret-scan.yml")
_ADR = os.path.join("docs", "decisions", "0027-no-history-rewrite.md")

# The three files the 2026-07-03 Phase 0 named. Kept explicit so a silent revert of any
# one of them fails, in addition to the repo-wide sweep below.
_SCRUBBED = (
    "HARNESS_SPEC.md",
    "progress.md",
    os.path.join("docs", "decisions", "0003-langfuse-integration.md"),
)

# A key literal is a Langfuse prefix followed by UUID-shaped material. Truncated
# references ("sk-lf-e220...") in incident write-ups are deliberately NOT matched.
_KEY_LITERAL = re.compile(r"\b[sp]k-lf-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")

_SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache"}


def _read(rel_path: str) -> str:
    with open(os.path.join(_ROOT, rel_path), encoding="utf-8") as fh:
        return fh.read()


def _markdown_files() -> list[str]:
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(_ROOT):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for name in filenames:
            if name.endswith(".md"):
                found.append(os.path.relpath(os.path.join(dirpath, name), _ROOT))
    return sorted(found)


def _check_config(errors: list[str]) -> None:
    """The config exists, extends the default ruleset, and carries no secret of its own."""
    if not os.path.exists(os.path.join(_ROOT, _CONFIG)):
        _check(False, f"{_CONFIG} exists", errors)
        return
    _check(True, f"{_CONFIG} exists", errors)
    config = _read(_CONFIG)
    _check("useDefault = true" in config, f"{_CONFIG} extends the built-in ruleset", errors)
    _check(
        not _KEY_LITERAL.search(config),
        f"{_CONFIG} stores no key literal (would defeat the working-tree gate)",
        errors,
    )


def _check_workflow(errors: list[str]) -> None:
    """Both scans are wired, with the working-tree one fail-closed."""
    if not os.path.exists(os.path.join(_ROOT, _WORKFLOW)):
        _check(False, f"{_WORKFLOW} exists", errors)
        return
    _check(True, f"{_WORKFLOW} exists", errors)
    workflow = _read(_WORKFLOW)
    _check("gitleaks" in workflow, f"{_WORKFLOW} runs gitleaks", errors)
    _check(
        "--no-git" in workflow and "--exit-code 0" in workflow,
        f"{_WORKFLOW} runs BOTH scans (working tree + history)",
        errors,
    )
    # Asserted per-line, not by whole-file substring: the report-only history flag must not
    # be able to satisfy a check about the working-tree line.
    worktree_lines = [ln for ln in workflow.splitlines() if "--no-git" in ln]
    _check(bool(worktree_lines), f"{_WORKFLOW} has a --no-git working-tree scan", errors)
    _check(
        all("--exit-code 0" not in ln for ln in worktree_lines),
        "the working-tree scan is FAIL-CLOSED (no --exit-code 0 on the --no-git line)",
        errors,
    )
    # Unfiltered, and asserted here rather than only in the test suite: a `paths:` filter
    # on this workflow is the defect that made the scan skippable, and it is invisible in
    # a diff that only adds four lines to a trigger block.
    import yaml

    document = yaml.safe_load(workflow) or {}
    # YAML 1.1 resolves the bare key `on:` to the boolean True, not the string "on" — the
    # long-standing "Norway problem" in GitHub Actions files. Accept either so this does
    # not depend on the loader's resolver version.
    triggers = document.get("on", document.get(True)) or {}
    pull_request = triggers.get("pull_request") or {}
    _check(
        "paths" not in pull_request and "paths-ignore" not in pull_request,
        "the scan runs on EVERY pull request (a credential can be committed in any file)",
        errors,
    )


def _check_no_key_literals(errors: list[str]) -> None:
    """The three named scrub targets, then a repo-wide markdown sweep."""
    for rel in _SCRUBBED:
        if not os.path.exists(os.path.join(_ROOT, rel)):
            _check(False, f"{rel} exists (scrub target)", errors)
            continue
        _check(not _KEY_LITERAL.search(_read(rel)), f"{rel} carries no key literal", errors)

    offenders = [rel for rel in _markdown_files() if _KEY_LITERAL.search(_read(rel))]
    _check(
        not offenders,
        f"no tracked markdown carries a key literal (offenders: {offenders})",
        errors,
    )


def main() -> int:
    configure_logging()
    errors: list[str] = []

    _check_config(errors)
    _check_workflow(errors)
    _check(os.path.exists(os.path.join(_ROOT, _ADR)), f"{_ADR} exists", errors)
    _check_no_key_literals(errors)

    return report(logger, "F-048", errors)


if __name__ == "__main__":
    raise SystemExit(main())
