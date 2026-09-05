#!/usr/bin/env python3
"""Every `uses:` in this repository is SHA-pinned, and its version comment tells the truth.

Two failures motivated this file, both found by reading rather than by any check:

* ``actions/upload-artifact@043fb46d…`` carried ``# v4`` in ``docs.yml`` and ``# v7.0.1``
  in ``quality-gates.yml`` — the SAME SHA, two versions, written by a single dependabot
  commit that preserved each file's existing comment format. Anyone auditing pins reads
  the comment, not the SHA, so ``docs.yml`` claimed a two-major-old action while running a
  current one. The comment is the human-readable half of the pin; a wrong one is worse
  than none.

* ``.github/actions/run-quality-gate/action.yml`` sat on ``setup-python@v5`` while every
  workflow ran ``v7.0.0``. Dependabot's ``github-actions`` ecosystem with ``directory: "/"``
  scans ``.github/workflows/`` and nothing else, so the composite action every one of those
  workflows delegates to was never updated — and the grouped bump pull requests looked
  complete. Fixed by giving the action its own dependabot entry; asserted here so a future
  ``.github/actions/<name>/`` is not added without one.

Derived from the files rather than allowlisted, in the repository's established idiom
(``check_guard_reachability``, ``test_required_check_stubs``).
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
ACTION_DIR = REPO_ROOT / ".github" / "actions"
DEPENDABOT = REPO_ROOT / ".github" / "dependabot.yml"

#: A pinned third-party step: `uses: owner/repo@<40 hex>  # comment`. Local `uses: ./...`
#: references are excluded — they are paths in this repository, not versioned dependencies.
_PINNED = re.compile(r"uses:\s*(?P<action>[\w.-]+/[\w./-]+)@(?P<sha>[0-9a-f]{40})\s*#\s*(?P<version>\S+)")

#: A `uses:` that is NOT a 40-hex pin and not a local path — the thing this repo forbids.
_UNPINNED = re.compile(r"uses:\s*(?P<ref>(?!\./)[\w.-]+/[\w./-]+@(?![0-9a-f]{40}\b)\S+)")


def _yaml_files() -> list[Path]:
    return sorted([*WORKFLOW_DIR.glob("*.yml"), *ACTION_DIR.glob("*/action.yml")])


def _pins() -> dict[tuple[str, str], set[str]]:
    """``(action, sha) -> {version comments seen}`` across every workflow and action."""
    seen: dict[tuple[str, str], set[str]] = defaultdict(set)
    for path in _yaml_files():
        for match in _PINNED.finditer(path.read_text(encoding="utf-8")):
            seen[(match["action"], match["sha"])].add(match["version"])
    return seen


def test_at_least_one_pin_is_found() -> None:
    """The regexes are the machinery; an empty sweep would make every test below vacuous."""
    assert len(_pins()) >= 3, "no pinned actions found — the parser, not the repository, is wrong"


def test_one_sha_never_carries_two_version_comments() -> None:
    """REGRESSION. `upload-artifact@043fb46d…` was `# v4` in one file and `# v7.0.1` in another."""
    conflicting = {
        f"{action}@{sha[:12]}": sorted(versions) for (action, sha), versions in _pins().items() if len(versions) > 1
    }
    assert not conflicting, f"the same SHA is documented as different versions: {conflicting}"


def test_one_version_comment_never_names_two_shas() -> None:
    """The other direction: `# v7.0.1` on two different SHAs means one of them moved.

    Tolerated for a bare-major comment (`# v4`), which legitimately spans many SHAs over
    time — but not for a resolved version, which names exactly one commit.
    """
    by_version: dict[tuple[str, str], set[str]] = defaultdict(set)
    for (action, sha), versions in _pins().items():
        for version in versions:
            if version.count(".") >= 1:  # a resolved tag, not a bare major
                by_version[(action, version)].add(sha)
    conflicting = {
        f"{action} {version}": sorted(s[:12] for s in shas)
        for (action, version), shas in by_version.items()
        if len(shas) > 1
    }
    assert not conflicting, f"one resolved version names several SHAs: {conflicting}"


@pytest.mark.parametrize("path", _yaml_files(), ids=lambda p: p.name if p.name != "action.yml" else p.parent.name)
def test_no_action_is_referenced_by_a_floating_tag(path: Path) -> None:
    """A mutable tag is not a pin: the same `@v4` can be re-pointed at any commit."""
    floating = sorted({m["ref"] for m in _UNPINNED.finditer(path.read_text(encoding="utf-8"))})
    assert not floating, f"{path.name} references actions by tag rather than SHA: {floating}"


def test_every_composite_action_directory_has_a_dependabot_entry() -> None:
    """REGRESSION. `directory: "/"` scans `.github/workflows/` ONLY.

    The composite action was two majors behind on `setup-python` because nothing scanned
    it, and the grouped bump pull requests gave no sign anything was missing.
    """
    document = yaml.safe_load(DEPENDABOT.read_text(encoding="utf-8"))
    watched = {update["directory"] for update in document["updates"] if update["package-ecosystem"] == "github-actions"}
    action_dirs = {f"/.github/actions/{path.parent.name}" for path in ACTION_DIR.glob("*/action.yml")}
    assert action_dirs <= watched, f"composite actions dependabot never scans: {sorted(action_dirs - watched)}"


def test_every_python_package_root_has_a_dependabot_entry() -> None:
    """A `pyproject.toml` outside a test fixture is a tree whose pins age.

    `experiments/backend-validation` was the gap: no CI job, no `coverage-floors.yaml`
    unit, no dependabot entry — and two 95% floors declared in its own pyproject.
    """
    document = yaml.safe_load(DEPENDABOT.read_text(encoding="utf-8"))
    watched = {update["directory"] for update in document["updates"] if update["package-ecosystem"] == "pip"}
    roots: set[str] = set()
    for path in REPO_ROOT.rglob("pyproject.toml"):
        relative = path.relative_to(REPO_ROOT)
        parts = relative.parts
        # Skip fixtures (a skill's eval inputs are not this repository's dependencies) and
        # anything inside a virtualenv or vendored tree.
        if any(part in {"evals", "fixtures", ".venv", "node_modules", "build", ".tox"} for part in parts):
            continue
        directory = "/" + "/".join(parts[:-1])
        roots.add(directory.rstrip("/") or "/")
    assert roots <= watched, f"python trees dependabot never scans: {sorted(roots - watched)}"
