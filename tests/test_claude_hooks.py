#!/usr/bin/env python3
"""The session hooks are wired, runnable, and advisory.

A hook is the easiest thing in this repository to leave half-configured: a file in
``.claude/hooks/`` that nothing in ``.claude/settings.json`` references never runs, and
nothing anywhere says so. That is the same "declared but never invoked" shape the M8
execution ledger exists to refuse, one directory over — so it gets the same treatment:
the two lists are derived from the files and compared, in both directions.

Behaviour is asserted by EXECUTION rather than by reading the source. Every hook here is
advisory by contract (exit 0, findings returned as ``additionalContext``, never a block),
and a hook that crashed or blocked would break every edit in a session — a failure nothing
else in this repository would catch, because hooks run in the agent's process and not in
CI.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK_DIR = REPO_ROOT / ".claude" / "hooks"
SETTINGS = REPO_ROOT / ".claude" / "settings.json"

#: Wall clock per hook invocation in these tests. The Stop hook regenerates the corpus to
#: answer its question, so it is the slow one.
_TIMEOUT_SECONDS = 120


def _settings() -> dict:
    loaded: dict = json.loads(SETTINGS.read_text(encoding="utf-8"))
    return loaded


def _referenced_hook_files() -> set[str]:
    """Every ``.claude/hooks/<name>`` a configured command mentions."""
    referenced: set[str] = set()
    for matchers in _settings()["hooks"].values():
        for matcher in matchers:
            for hook in matcher["hooks"]:
                for token in hook["command"].split():
                    marker = ".claude/hooks/"
                    if marker in token:
                        referenced.add(token.split(marker, 1)[1].strip("\"'"))
    return referenced


def _hook_files() -> set[str]:
    return {path.name for path in HOOK_DIR.iterdir() if path.is_file()}


def test_every_hook_file_is_referenced_by_the_settings() -> None:
    """A hook nothing invokes is dead code that looks like a guard."""
    assert _hook_files() <= _referenced_hook_files(), (
        f"hooks present but never configured: {sorted(_hook_files() - _referenced_hook_files())}"
    )


def test_every_configured_hook_file_exists_and_is_executable() -> None:
    """The other direction: a renamed hook leaves a command that fails on every edit."""
    missing = sorted(name for name in _referenced_hook_files() if not (HOOK_DIR / name).is_file())
    assert not missing, f"settings.json references hooks that do not exist: {missing}"
    not_executable = sorted(name for name in _referenced_hook_files() if not os.access(HOOK_DIR / name, os.X_OK))
    assert not not_executable, f"hooks are not executable: {not_executable}"


def _hook_module(hook: str, alias: str) -> Any:
    """Import a hook by path so its internals can be driven directly.

    Typed ``Any`` deliberately: a module loaded from a path has no static type, and the
    two tests below reach for private names on purpose — driving `_CHECKERS` with a
    command that reports drift is what makes the staleness branch reachable without
    dirtying the real committed artifact.
    """
    spec = importlib.util.spec_from_file_location(alias, HOOK_DIR / hook)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(hook: str, event: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HOOK_DIR / hook)],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
        cwd=REPO_ROOT,
    )


@pytest.mark.parametrize("hook", sorted(name for name in _hook_files() if name.endswith(".py")))
def test_a_python_hook_never_fails_a_turn(hook: str) -> None:
    """Fail-open is the contract: a hook that exits non-zero breaks the tool call it follows.

    Exercised with a deliberately malformed event, which is the shape most likely to reach
    an exception path: a hook that only handles the events it expects is a hook that will
    one day block an edit for a reason nobody can see.
    """
    assert _run(hook, {"tool_input": {"file_path": "/nonexistent/\x00"}}).returncode == 0
    assert _run(hook, {}).returncode == 0


def test_the_protected_path_hook_reports_a_protected_file() -> None:
    """Asserted by running it, against a path the real guard actually protects."""
    result = _run("post-edit-protected-path.py", {"tool_input": {"file_path": str(REPO_ROOT / "features.yaml")}})
    payload = json.loads(result.stdout)
    context = payload["hookSpecificOutput"]["additionalContext"]
    assert "features.yaml" in context
    assert "eval-change-approved" in context, "the message must name the label a reviewer needs"


def test_the_protected_path_hook_stays_silent_on_an_unprotected_file() -> None:
    """The negative control: a hook that fires on everything is noise, not a signal."""
    result = _run("post-edit-protected-path.py", {"tool_input": {"file_path": str(REPO_ROOT / "README.md")}})
    assert result.stdout.strip() == ""


def test_the_stop_hook_is_silent_when_every_artifact_is_fresh() -> None:
    """It must not cry wolf on a clean tree — CI's own freshness gates are green here."""
    assert _run("stop-generated-artifacts.py", {}).stdout.strip() == ""


def test_the_stop_hook_reports_a_stale_artifact(tmp_path: Path) -> None:
    """REGRESSION-shaped: the hook exists because these go stale unnoticed.

    Rather than dirtying the real committed artifact, the checker table is driven with a
    command that reports drift, which is the only thing `_stale` reads.
    """
    module = _hook_module("stop-generated-artifacts.py", "_stop_hook")
    failing = tmp_path / "always_stale.py"
    failing.write_text("import sys\nsys.exit(1)\n", encoding="utf-8")
    module._CHECKERS = ((("some/artifact"), (str(failing),), "regenerate it"),)
    findings = module._findings()
    assert findings == ["some/artifact is stale — regenerate and commit: regenerate it"]


def test_the_stop_hook_treats_a_missing_checker_as_unknown_not_stale() -> None:
    """ "Cannot tell" must never be reported as a finding, or the hook trains people to
    ignore it — the same reasoning `scripts/_provenance.py` applies to a shallow clone."""
    module = _hook_module("stop-generated-artifacts.py", "_stop_hook2")
    assert module._stale(("scripts/does_not_exist.py", "--check")) is False
