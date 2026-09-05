#!/usr/bin/env python3
"""Tests for scripts/_provenance.py — does a recorded commit exist, and did it land?

The central case here is the one a resolution-only check cannot see: a ref that resolves
perfectly and is on a branch that never merged. It is tested against a real two-branch
repository (``_gitrepo``) rather than a stub, because a stub returning a canned exit code
would assert the stub. F-040 carried exactly that defect for six weeks while CI reported
the ledger clean.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any

import _provenance as prov
import pytest

from tests import _gitrepo as gr

# --------------------------------------------------------------------------- helpers

#: A syntactically valid SHA that no repository contains.
ABSENT_SHA = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"

#: Branch a fixture's unlanded work lives on. Named so the assertions can say why a ref is
#: expected to fail rather than restating a literal.
UNMERGED_BRANCH = "feat/never-merged"


def _feat(fid: str, implemented_in: str | None = None) -> dict[str, Any]:
    """The smallest ledger entry these functions read: an id and maybe a ref."""
    feat: dict[str, Any] = {"id": fid}
    if implemented_in is not None:
        feat["implemented_in"] = implemented_in
    return feat


@pytest.fixture
def landed_and_unlanded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str, str]:
    """A repo whose HEAD is on the default branch, with one commit stranded elsewhere.

    Returns ``(repo, landed_sha, unlanded_sha)``. Both SHAs resolve; only one is reachable
    from HEAD. That asymmetry is the entire subject of this module.
    """
    repo = gr.init_repo(tmp_path / "repo")
    landed = gr.commit(repo, "landed work")
    gr.new_branch(repo, UNMERGED_BRANCH)
    unlanded = gr.commit(repo, "work that never merged")
    gr.checkout(repo, gr.DEFAULT_BRANCH)
    monkeypatch.chdir(repo)
    return repo, landed, unlanded


# --------------------------------------------------------------------------- ref_problem


def test_a_landed_ref_is_sound(landed_and_unlanded: tuple[Path, str, str]) -> None:
    _repo, landed, _unlanded = landed_and_unlanded
    assert prov.ref_problem(landed) is None


def test_an_unmerged_branch_ref_resolves_and_is_still_a_problem(
    landed_and_unlanded: tuple[Path, str, str],
) -> None:
    """The defect a resolution-only check reports as healthy.

    The two assertions are the whole finding: `rev-parse` succeeds, and the ref is still
    bad. CI clones with `fetch-depth: 0`, which fetches every branch, so this is precisely
    the shape that passed for six weeks.
    """
    repo, _landed, unlanded = landed_and_unlanded

    resolved = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{unlanded}^{{commit}}"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert resolved.returncode == 0, "precondition: the ref must genuinely resolve"

    problem = prov.ref_problem(unlanded)
    assert problem is not None
    assert "not an ancestor" in problem


def test_an_absent_ref_is_reported_as_unresolvable_not_as_unlanded(
    landed_and_unlanded: tuple[Path, str, str],
) -> None:
    """Two defects, two fixes, two messages — a missing object is not an unmerged branch."""
    problem = prov.ref_problem(ABSENT_SHA)
    assert problem == "does not resolve"


def test_an_in_flight_ref_passes_on_its_own_branch(landed_and_unlanded: tuple[Path, str, str]) -> None:
    """Why the target is HEAD and not origin/main.

    A PR stamping its own feature's SHA records a commit on its own branch. Measured
    against `origin/main` that legitimate case fails and the guard needs an exemption list;
    measured against HEAD it simply passes, and the same ref still fails from elsewhere.
    """
    repo, _landed, unlanded = landed_and_unlanded
    gr.checkout(repo, UNMERGED_BRANCH)
    assert prov.ref_problem(unlanded) is None, "a stamp on the current branch is legitimate provenance"

    gr.checkout(repo, gr.DEFAULT_BRANCH)
    assert prov.ref_problem(unlanded) is not None, "and the same ref is still caught from the default branch"


def test_ancestry_ref_is_a_parameter_not_a_baked_in_literal(
    landed_and_unlanded: tuple[Path, str, str],
) -> None:
    """The same ref, judged against two revisions, gives two answers."""
    _repo, _landed, unlanded = landed_and_unlanded
    assert prov.ref_problem(unlanded, ancestry_ref=gr.DEFAULT_BRANCH) is not None
    assert prov.ref_problem(unlanded, ancestry_ref=UNMERGED_BRANCH) is None


def test_an_undecidable_ancestry_is_reported_not_swallowed(
    landed_and_unlanded: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`merge-base --is-ancestor` answers 0 or 1; anything else means it did not answer.

    Passing a check that measured nothing is the failure this module exists to prevent, so
    an unexpected exit is a finding rather than a silent `None`.
    """
    _repo, landed, _unlanded = landed_and_unlanded
    real = prov.run_git

    def flaky(args: list[str]) -> Any:
        if args[:2] == ["merge-base", "--is-ancestor"]:
            return subprocess.CompletedProcess(args, returncode=128, stdout="", stderr="fatal: bad object")
        return real(args)

    monkeypatch.setattr(prov, "run_git", flaky)
    problem = prov.ref_problem(landed)
    assert problem is not None
    assert "could not be determined" in problem
    assert "fatal: bad object" in problem


def test_git_vanishing_between_the_two_calls_is_reported(
    landed_and_unlanded: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`run_git` returns None when git is gone; the second call must handle it."""
    _repo, landed, _unlanded = landed_and_unlanded
    real = prov.run_git

    def vanishing(args: list[str]) -> Any:
        return None if args[:2] == ["merge-base", "--is-ancestor"] else real(args)

    monkeypatch.setattr(prov, "run_git", vanishing)
    problem = prov.ref_problem(landed)
    assert problem is not None
    assert "became unavailable" in problem


# --------------------------------------------------------------------------- check_refs


def test_check_refs_flags_the_unlanded_entry_under_strict(landed_and_unlanded: tuple[Path, str, str]) -> None:
    _repo, landed, unlanded = landed_and_unlanded
    feats = [_feat("F-001", landed), _feat("F-002", unlanded), _feat("F-003")]

    assert prov.check_refs(feats, strict=False) == [], "without strict, findings are warnings"

    errors = prov.check_refs(feats, strict=True)
    assert len(errors) == 1
    assert "F-002" in errors[0] and "not an ancestor" in errors[0]


def test_a_feature_without_a_ref_is_not_a_finding(landed_and_unlanded: tuple[Path, str, str]) -> None:
    """`implemented_in` is optional; only a *present but bad* ref is a defect."""
    assert prov.check_refs([_feat("F-001")], strict=True) == []


def test_one_probe_per_distinct_ref_not_per_feature(landed_and_unlanded: tuple[Path, str, str]) -> None:
    """Several features can share one landing commit — five do in the live ledger."""
    _repo, landed, _unlanded = landed_and_unlanded
    calls: list[str] = []

    def counting(ref: str, *, ancestry_ref: str) -> str | None:
        calls.append(ref)
        return None

    feats = [_feat(f"F-00{i}", landed) for i in range(1, 6)]
    assert prov.check_refs(feats, strict=True, ref_probe=counting) == []
    assert calls == [landed], "five features sharing a ref must cost one probe"


def test_every_feature_sharing_a_bad_ref_is_named(landed_and_unlanded: tuple[Path, str, str]) -> None:
    """Deduplicating the git calls must not deduplicate the findings."""
    _repo, _landed, unlanded = landed_and_unlanded
    feats = [_feat("F-001", unlanded), _feat("F-002", unlanded)]
    errors = prov.check_refs(feats, strict=True)
    assert {"F-001", "F-002"} == {e.split()[1] for e in errors}


def test_shallow_clone_downgrades_strict_to_warnings(
    landed_and_unlanded: tuple[Path, str, str], caplog: pytest.LogCaptureFixture
) -> None:
    """Reachability is unanswerable on grafted history, so a shallow clone must not report.

    Injected rather than monkeypatched: the probe seam exists so a substitution is visible
    at the call site and survives the code moving between modules.
    """
    _repo, _landed, unlanded = landed_and_unlanded
    feats = [_feat("F-001", unlanded)]
    with caplog.at_level(logging.WARNING):
        assert prov.check_refs(feats, strict=True, shallow_probe=lambda: True) == []
    assert any("shallow clone" in r.getMessage() for r in caplog.records)


def test_missing_git_is_an_error_under_strict_and_a_warning_without(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Nothing was measured, and a check that measured nothing must not report success."""

    def boom(*_a: Any, **_k: Any) -> Any:
        raise FileNotFoundError(2, "No such file or directory: 'git'")

    monkeypatch.setattr(prov.subprocess, "run", boom)
    feats = [_feat("F-001", ABSENT_SHA)]

    assert prov.check_refs(feats, strict=True) == [prov.GIT_MISSING_MESSAGE]
    with caplog.at_level(logging.WARNING):
        assert prov.check_refs(feats, strict=False) == []
    assert any(prov.GIT_MISSING_MESSAGE in r.getMessage() for r in caplog.records)


def test_missing_git_with_nothing_to_verify_is_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    """No refs means nothing to verify; an absent git is then not worth reporting."""

    def boom(*_a: Any, **_k: Any) -> Any:
        raise FileNotFoundError(2, "No such file or directory: 'git'")

    monkeypatch.setattr(prov.subprocess, "run", boom)
    assert prov.check_refs([_feat("F-001")], strict=True) == []


def test_run_git_returns_none_when_git_is_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: Any, **_k: Any) -> Any:
        raise FileNotFoundError(2, "No such file or directory: 'git'")

    monkeypatch.setattr(prov.subprocess, "run", boom)
    assert prov.run_git(["rev-parse", "HEAD"]) is None


def test_is_shallow_clone_does_not_crash_without_git(monkeypatch: pytest.MonkeyPatch) -> None:
    """ "Cannot tell" is not "shallow" — the missing-git case is handled explicitly."""

    def boom(*_a: Any, **_k: Any) -> Any:
        raise FileNotFoundError(2, "No such file or directory: 'git'")

    monkeypatch.setattr(prov.subprocess, "run", boom)
    assert prov.is_shallow_clone() is False


def test_is_shallow_clone_answers_for_a_real_repository(landed_and_unlanded: tuple[Path, str, str]) -> None:
    """A freshly initialised repository is complete by construction."""
    assert prov.is_shallow_clone() is False


# --------------------------------------------------------------------------- the ledger


def test_the_live_ledger_has_no_unlanded_provenance() -> None:
    """Every `implemented_in` in features.yaml is reachable from this checkout's HEAD.

    The regression test for the finding itself. Skipped on a shallow clone for the same
    reason `check_refs` downgrades there: the answer would be about the clone, not the
    ledger.
    """
    if prov.is_shallow_clone():
        pytest.skip("shallow clone: reachability is unanswerable on grafted history")

    import yaml

    root = Path(__file__).resolve().parent.parent
    features = yaml.safe_load((root / "features.yaml").read_text(encoding="utf-8"))["features"]
    assert prov.check_refs(features, strict=True) == []
