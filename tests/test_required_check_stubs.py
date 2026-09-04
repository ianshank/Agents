"""The stub/real check-name pairing is a contract, so assert it mechanically.

``.github/workflows/required-check-stubs.yml`` posts a green check for every
context ADR 0037 would require, but only on pull requests where the real
workflow's ``paths:`` filter did not fire. That works only while each stub job's
rendered ``name:`` is byte-identical to the real job's. The workflow's own
maintenance note calls those names "the contract" and spells out both failure
modes:

* Rename a real job and not its stub, and the required context goes unreported
  on docs-only pull requests -- a permanent merge deadlock, which is the exact
  problem the stubs exist to prevent.
* Add a real job to a stubbed workflow and forget its stub, and the same
  deadlock appears for the new context.

A note is not a gate. Nothing else in the repository re-checks this, and the
failure is invisible until someone opens a pull request that happens to touch
only unfiltered paths -- the same "ungated code rots silently" shape that left
two demo configs broken for two weeks. So this module derives both sides from
the workflow files and compares them, in the repository's established
derive-never-allowlist idiom (``check_guard_reachability``, the ``all-skills``
meta-gate).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOW_DIR = Path(__file__).resolve().parent.parent / ".github" / "workflows"
STUB_WORKFLOW = WORKFLOW_DIR / "required-check-stubs.yml"

#: How a stub job declares which real workflow it stands in for.
_GATE_CONDITION = re.compile(r"needs\.gate\.outputs\.(?P<key>\w+)\s*==\s*'false'")

#: The gate job's own WORKFLOWS mapping, parsed out of its inline Python. Read
#: from the workflow rather than restated here, so this test cannot pass against
#: a stale copy of the list it is meant to be checking.
_WORKFLOWS_ENTRY = re.compile(r'^\s*"(?P<key>\w+)":\s*"(?P<path>\.github/workflows/[\w.-]+\.yml)",\s*$')


def _load(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{path} is not a YAML mapping"
    return data


def _rendered_job_names(workflow: dict[str, Any]) -> set[str]:
    """Every check context *workflow* can post.

    A matrix job's ``name:`` expands once per matrix value, which is what makes
    it a distinct check context. Only ``python-version`` is expanded: it is the
    single matrix axis in use across this repository, and a silent wrong answer
    would be worse than an explicit failure, so anything else raises.
    """
    names: set[str] = set()
    for job_id, job in workflow.get("jobs", {}).items():
        name = job.get("name", job_id)
        matrix = job.get("strategy", {}).get("matrix", {})
        axes = {k: v for k, v in matrix.items() if k != "fail-fast"}
        if not axes:
            assert "${{" not in name, f"job {job_id!r} interpolates {name!r} with no matrix to expand"
            names.add(name)
            continue
        assert set(axes) == {"python-version"}, f"job {job_id!r} has an unsupported matrix axis: {sorted(axes)}"
        for version in axes["python-version"]:
            names.add(name.replace("${{ matrix.python-version }}", str(version)))
    return names


def _gate_workflow_map() -> dict[str, Path]:
    """The gate job's ``key -> workflow file`` mapping, read from its own source."""
    text = STUB_WORKFLOW.read_text(encoding="utf-8")
    mapping = {
        m.group("key"): WORKFLOW_DIR.parent.parent / m.group("path")
        for m in map(_WORKFLOWS_ENTRY.match, text.splitlines())
        if m
    }
    assert mapping, "could not parse the gate job's WORKFLOWS mapping"
    return mapping


def _stub_names_by_key() -> dict[str, set[str]]:
    """Rendered stub names, grouped by the gate output each is conditioned on."""
    stubs = _load(STUB_WORKFLOW)
    grouped: dict[str, set[str]] = {}
    for job_id, job in stubs["jobs"].items():
        condition = str(job.get("if", ""))
        match = _GATE_CONDITION.search(condition)
        if not match:
            continue  # the gate job itself, which is machinery rather than a stub
        single = {"jobs": {job_id: job}}
        grouped.setdefault(match.group("key"), set()).update(_rendered_job_names(single))
    return grouped


GATE_MAP = _gate_workflow_map()


def test_every_mapped_workflow_exists() -> None:
    for key, path in GATE_MAP.items():
        assert path.is_file(), f"gate key {key!r} points at a missing workflow: {path}"


@pytest.mark.parametrize("key", sorted(GATE_MAP))
def test_stub_names_match_the_real_workflow_exactly(key: str) -> None:
    """Both directions, because each failure mode is a merge deadlock.

    A missing stub leaves a required context unreported on a docs-only pull
    request. An extra stub posts a context nothing requires, which is the
    duplicate-context hazard ADR 0040's namespacing exists to remove.
    """
    real = _rendered_job_names(_load(GATE_MAP[key]))
    stubs = _stub_names_by_key().get(key, set())

    assert stubs == real, (
        f"stub/real check-name drift for {key!r} ({GATE_MAP[key].name}): "
        f"missing stubs {sorted(real - stubs)}, orphan stubs {sorted(stubs - real)}"
    )


def test_no_stub_is_orphaned_from_the_gate_map() -> None:
    assert set(_stub_names_by_key()) <= set(GATE_MAP)


def test_stub_workflow_runs_on_every_pull_request() -> None:
    """The gate cannot decide for a workflow run that never starts, so the stub
    workflow itself must carry no ``paths:`` filter."""
    workflow = _load(STUB_WORKFLOW)
    # YAML 1.1 resolves the bare key `on:` to the boolean True, not the string
    # "on" -- the long-standing "Norway problem" in GitHub Actions files. Accept
    # either so this does not depend on the loader's resolver version.
    triggers = workflow.get("on", workflow.get(True))  # type: ignore[call-overload]
    assert triggers is not None, "stub workflow declares no triggers"
    trigger = triggers["pull_request"]

    assert "paths" not in trigger
    assert "paths-ignore" not in trigger


def test_stub_jobs_do_no_work() -> None:
    """A stub reports a context; it must never be mistaken for having run a suite."""
    for job_id, job in _load(STUB_WORKFLOW)["jobs"].items():
        if job_id == "gate":
            continue
        steps = job["steps"]
        assert len(steps) == 1, f"stub {job_id!r} should have exactly one step"
        assert "run" in steps[0] and "uses" not in steps[0], f"stub {job_id!r} must not use an action"
