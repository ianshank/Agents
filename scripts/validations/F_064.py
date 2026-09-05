#!/usr/bin/env python3
"""Validation script for F-064 - ledger provenance: implemented_in must have landed.

Implements ``docs/plans/eval-delivery-sequencing/PLAN.md`` WS-1. The ledger records an
``implemented_in`` SHA per feature and ``validate.py --strict-git`` verified that the SHA
was *a commit*. It never verified that the commit was in this history, and CI clones with
``fetch-depth: 0`` — which fetches every branch — so a commit on a branch that never merged
resolved perfectly. F-040 carried exactly that for six weeks: its ref lived only on the
pre-rebase ``feat/F-040-soak-stats``, while the work had landed via PR #113 from the
rebased branch.

Checks:
    1.  The ancestry question is asked at all, and is asked against a *parameter*:
        ``ANCESTRY_REF`` is ``HEAD``, and pointing the check at a different revision
        changes its answer for the same ref.
    2.  The F-040 shape is refused -- established by BUILDING a two-branch repository and
        running the real check inside it, not by inspecting source. The ref is proved to
        resolve first, so the check cannot be passing for the trivial reason.
    3.  An in-flight stamp on the current branch is accepted, which is why ``HEAD`` needs
        no exemption list for refs a pull request introduces.
    4.  The pre-existing resolution check still reports an absent object as "does not
        resolve" -- two defects with two fixes must not collapse into one message.
    5.  Strict posture is unchanged: findings are errors under strict and warnings without
        it, and a shallow clone downgrades, because reachability is unanswerable on
        grafted history.
    6.  The live ledger passes: every ``implemented_in`` in ``features.yaml`` is reachable
        from this checkout's HEAD.
    7.  CI actually runs the guard, so none of the above is decorative.

Exit codes:
    0 - all checks passed
    1 - one or more checks failed
"""

from __future__ import annotations

import contextlib
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from _common import check as _check
from _common import ci_enforces, configure_logging, report

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts"))
sys.path.insert(0, PROJECT_ROOT)

#: Branch the fixture's unlanded commit lives on. The F-040 shape, reproduced.
_UNMERGED_BRANCH = "feat/never-merged"

#: A syntactically valid SHA no repository contains.
_ABSENT_SHA = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"

#: Workflow that must run the guard, and the command that constitutes running it.
_GUARD_WORKFLOW = os.path.join(PROJECT_ROOT, ".github", "workflows", "quality-gates.yml")
_GUARD_COMMAND = "--strict-git"


def _feat(fid: str, implemented_in: str | None = None) -> dict[str, Any]:
    feat: dict[str, Any] = {"id": fid}
    if implemented_in is not None:
        feat["implemented_in"] = implemented_in
    return feat


@contextlib.contextmanager
def _two_branch_repo() -> Any:
    """Yield ``(landed_sha, unlanded_sha)`` with the process inside a fixture repository.

    Both SHAs resolve; only one is reachable from HEAD. Built with the same helper the
    pytest suite uses (``tests/_gitrepo.py``) so the two cannot drift apart.
    """
    from tests import _gitrepo as gr

    with tempfile.TemporaryDirectory() as tmp:
        repo = gr.init_repo(Path(tmp) / "repo")
        landed = gr.commit(repo, "landed work")
        gr.new_branch(repo, _UNMERGED_BRANCH)
        unlanded = gr.commit(repo, "work that never merged")
        gr.checkout(repo, gr.DEFAULT_BRANCH)
        with contextlib.chdir(repo):
            yield landed, unlanded


def _check_ancestry_is_asked_and_parameterised(errors: list[str]) -> None:
    import _provenance as prov

    _check(
        prov.ANCESTRY_REF == "HEAD",
        "ancestry is measured against HEAD (a PR's own in-flight stamp is on its branch, "
        "so origin/main would need an exemption list)",
        errors,
    )
    with _two_branch_repo() as (_landed, unlanded):
        from tests import _gitrepo as gr

        _check(
            prov.ref_problem(unlanded, ancestry_ref=gr.DEFAULT_BRANCH) is not None
            and prov.ref_problem(unlanded, ancestry_ref=_UNMERGED_BRANCH) is None,
            "the ancestry target is a real parameter: the same ref answers differently against two revisions",
            errors,
        )


def _check_the_f040_shape_is_refused(errors: list[str]) -> None:
    """Build the defect and watch the guard catch it. Source inspection would prove nothing."""
    import _provenance as prov

    with _two_branch_repo() as (_landed, unlanded):
        resolved = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"{unlanded}^{{commit}}"],
            capture_output=True,
            text=True,
        )
        if not _check(
            resolved.returncode == 0,
            "precondition: the unlanded ref genuinely resolves, so the check below cannot "
            "be passing merely because the object is missing",
            errors,
        ):
            return

        errs = prov.check_refs([_feat("F-XXX", unlanded)], strict=True)
        _check(
            len(errs) == 1 and "not an ancestor" in errs[0],
            f"a ref that resolves but is on a branch that never landed is refused (observed: {errs or 'no finding'})",
            errors,
        )


def _check_in_flight_stamp_is_accepted(errors: list[str]) -> None:
    import _provenance as prov

    with _two_branch_repo() as (_landed, unlanded):
        from tests import _gitrepo as gr

        gr.checkout(Path.cwd(), _UNMERGED_BRANCH)
        accepted = prov.check_refs([_feat("F-XXX", unlanded)], strict=True) == []
        gr.checkout(Path.cwd(), gr.DEFAULT_BRANCH)
        refused = prov.check_refs([_feat("F-XXX", unlanded)], strict=True) != []

    _check(
        accepted and refused,
        "the same ref is accepted from its own branch and refused from the default branch "
        "-- which is what lets a PR stamp its own SHA with no exemption list",
        errors,
    )


def _check_resolution_defect_is_still_distinct(errors: list[str]) -> None:
    import _provenance as prov

    with _two_branch_repo() as (_landed, _unlanded):
        _check(
            prov.ref_problem(_ABSENT_SHA) == "does not resolve",
            "an absent object is still reported as 'does not resolve', not as unlanded "
            "-- two defects with two different fixes",
            errors,
        )


def _check_strict_posture_is_unchanged(errors: list[str]) -> None:
    import _provenance as prov

    with _two_branch_repo() as (_landed, unlanded):
        feats = [_feat("F-XXX", unlanded)]
        _check(
            prov.check_refs(feats, strict=False) == [],
            "without strict, a finding is a warning and not an error",
            errors,
        )
        _check(
            prov.check_refs(feats, strict=True, shallow_probe=lambda: True) == [],
            "a shallow clone downgrades strict to warnings: reachability is unanswerable on grafted history",
            errors,
        )


def _check_the_live_ledger_has_landed_provenance(errors: list[str]) -> None:
    import _provenance as prov
    import yaml

    if prov.is_shallow_clone():
        logger.warning("shallow clone: skipping the live-ledger check, its answer would be about the clone")
        return

    features_path = Path(PROJECT_ROOT) / "features.yaml"
    features = yaml.safe_load(features_path.read_text(encoding="utf-8"))["features"]
    stamped = [f for f in features if f.get("implemented_in")]
    problems = prov.check_refs(features, strict=True)
    _check(
        not problems,
        f"every implemented_in ref in features.yaml is reachable from HEAD "
        f"({len(stamped)} stamped) -- unresolved: {problems}",
        errors,
    )


def _check_ci_runs_the_guard(errors: list[str]) -> None:
    """A guard CI does not run is a guard that does not exist."""
    workflow = Path(_GUARD_WORKFLOW).read_text(encoding="utf-8")
    gate = (Path(PROJECT_ROOT) / "scripts" / "quality-gate.sh").read_text(encoding="utf-8")
    _check(
        ci_enforces(workflow, gate, inline=_GUARD_COMMAND, in_gate=_GUARD_COMMAND),
        f"CI runs validate.py with {_GUARD_COMMAND}, so the ancestry check is enforced rather than merely available",
        errors,
    )


def main() -> int:
    configure_logging()
    errors: list[str] = []
    _check_ancestry_is_asked_and_parameterised(errors)
    _check_the_f040_shape_is_refused(errors)
    _check_in_flight_stamp_is_accepted(errors)
    _check_resolution_defect_is_still_distinct(errors)
    _check_strict_posture_is_unchanged(errors)
    _check_the_live_ledger_has_landed_provenance(errors)
    _check_ci_runs_the_guard(errors)
    return report(logger, "F-064", errors)


if __name__ == "__main__":
    sys.exit(main())
