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

#: The matrix expression to expand when rendering a job name into a check
#: context. Matched as a pattern, not a literal substring: GitHub treats
#: whitespace inside ``${{ ... }}`` as insignificant, so ``${{matrix.python-version}}``
#: renders identically. A literal ``.replace`` would silently miss a reformatted
#: expression on one side of the stub/real comparison and report drift that
#: is not there -- or, worse, agree because both sides failed to render.
_PYTHON_VERSION_EXPR = re.compile(r"\$\{\{\s*matrix\.python-version\s*\}\}")

#: The gate job's own ``--workflow KEY=PATH`` arguments to
#: ``scripts/workflow_paths.py``. Read from the workflow rather than restated
#: here, so this test cannot pass against a stale copy of the list it checks.
_WORKFLOWS_ENTRY = re.compile(r"--workflow\s+(?P<key>\w+)=(?P<path>\.github/workflows/[\w.-]+\.yml)")


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
            rendered = _PYTHON_VERSION_EXPR.sub(str(version), name)
            # Substitution must be total. Comparing a half-rendered name against
            # another half-rendered one would agree for the wrong reason, and this
            # test's entire job is to catch names that disagree.
            assert "${{" not in rendered, f"job {job_id!r} has an expression this test cannot render: {name!r}"
            names.add(rendered)
    return names


def _gate_workflow_map() -> dict[str, Path]:
    """The gate job's ``key -> workflow file`` mapping, read from its own source."""
    text = STUB_WORKFLOW.read_text(encoding="utf-8")
    mapping = {m.group("key"): WORKFLOW_DIR.parent.parent / m.group("path") for m in _WORKFLOWS_ENTRY.finditer(text)}
    assert mapping, "could not parse the gate job's --workflow arguments"
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


def test_the_secret_scan_carries_no_paths_filter_and_needs_no_stub() -> None:
    """REGRESSION. A stub for gitleaks was worse than no check at all.

    `paths:` is evaluated per WORKFLOW. gitleaks lived in `quality-gates.yml`, so a pull
    request touching only docs, demos, skills or a corpus never started that workflow, and
    the companion stub then reported `secret scan (gitleaks)` GREEN — a passing secret scan
    that no scanner produced, on exactly the changes least likely to be read line by line.

    Every other stub stands in for a suite whose filter genuinely means "this change cannot
    affect that suite". No filter can mean that about a credential, which can be committed
    in any file. So this asserts the two halves of the fix together: the scan is unfiltered,
    and therefore has no stub (a second job posting the same context would be the
    duplicate-green hazard this workflow's own header warns about).
    """
    workflow = _load(WORKFLOW_DIR / "secret-scan.yml")
    triggers = workflow.get("on", workflow.get(True))  # type: ignore[call-overload]
    assert triggers is not None, "secret-scan workflow declares no triggers"
    trigger = triggers["pull_request"]
    assert "paths" not in trigger, "a credential can be committed in any file"
    assert "paths-ignore" not in trigger

    names = _rendered_job_names(workflow)
    assert "secret scan (gitleaks)" in names, "the required check context must not be renamed"
    stubbed = {name for names_ in _stub_names_by_key().values() for name in names_}
    assert not (names & stubbed), "an unfiltered job must not also be stubbed"


def test_stub_jobs_do_no_work() -> None:
    """A stub reports a context; it must never be mistaken for having run a suite."""
    for job_id, job in _load(STUB_WORKFLOW)["jobs"].items():
        if job_id == "gate":
            continue
        steps = job["steps"]
        assert len(steps) == 1, f"stub {job_id!r} should have exactly one step"
        assert "run" in steps[0] and "uses" not in steps[0], f"stub {job_id!r} must not use an action"


def test_matrix_expansion_tolerates_reformatted_whitespace() -> None:
    """GitHub treats whitespace inside ``${{ }}`` as insignificant.

    A literal-substring replace would miss a reformatted expression, leaving the
    name unrendered on one side of the comparison. Pinned because reformatting a
    workflow is exactly the kind of harmless edit that should not break a gate.
    """
    spaced = {
        "jobs": {
            "a": {"name": "pkg py${{ matrix.python-version }}", "strategy": {"matrix": {"python-version": ["3.12"]}}}
        }
    }
    tight = {
        "jobs": {
            "a": {"name": "pkg py${{matrix.python-version}}", "strategy": {"matrix": {"python-version": ["3.12"]}}}
        }
    }

    assert _rendered_job_names(spaced) == _rendered_job_names(tight) == {"pkg py3.12"}


def test_an_unrenderable_expression_fails_loudly() -> None:
    """Half-rendered names could agree for the wrong reason, so refuse to compare them."""
    workflow = {"jobs": {"a": {"name": "pkg ${{ matrix.os }}", "strategy": {"matrix": {"python-version": ["3.12"]}}}}}

    with pytest.raises(AssertionError, match="cannot render"):
        _rendered_job_names(workflow)
