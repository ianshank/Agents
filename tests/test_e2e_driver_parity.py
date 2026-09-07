"""The POSIX e2e driver must declare exactly the steps the matrix engine can see.

``tests/_e2e_matrix.py`` parses ``scripts/run_all_e2e.ps1`` for the declared step
inventory and hard-fails any run whose report contains a step the parser cannot
see (``policy_problems``). ``scripts/run_all_e2e.sh`` is the POSIX mirror of that
runner: it exists so the nightly freshness job can produce a run report on
``ubuntu-latest`` (the .ps1 driver has never run in CI). The mirror is only safe
if the two drivers can never drift apart, so this module derives both inventories
and compares them -- the same derive-never-allowlist idiom as
``test_required_check_stubs.py``.

Bash call convention the extraction relies on (keep it when editing the driver):
step-recording helpers take the tier as ``$1`` and the step name as ``$2``, both
as literal words or single-quoted strings -- never variables. Calls that use
``"$tier"``/``"$name"`` (inside the helper bodies) are not declarations.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests import _e2e_matrix as em

ROOT = Path(__file__).resolve().parent.parent
BASH_DRIVER = ROOT / "scripts" / "run_all_e2e.sh"
PS1_DRIVER = ROOT / "scripts" / "run_all_e2e.ps1"

#: Step-recording call sites in the bash driver: `helper TIER NAME ...` where both
#: arguments are literal (bare word or single-quoted). Variable arguments (``$tier``)
#: are helper-body plumbing, not declarations, and are deliberately not matched.
_BASH_STEP_RE = re.compile(
    r"^\s*(?:invoke_pytest_step|invoke_cmd_step|add_result|test_step_script)"
    r"\s+(?:'(?P<tier_q>[^']+)'|(?P<tier_b>[A-Z]+))"
    r"\s+(?:'(?P<name_q>[^']+)'|(?P<name_b>[A-Za-z0-9_:+().-]+))",
    re.MULTILINE,
)


def _bash_declared_steps() -> set[tuple[str, str]]:
    """(tier, name) pairs the bash driver can record, derived from its call sites."""
    text = BASH_DRIVER.read_text(encoding="utf-8")
    steps: set[tuple[str, str]] = set()
    for match in _BASH_STEP_RE.finditer(text):
        tier = match.group("tier_q") or match.group("tier_b")
        name = match.group("name_q") or match.group("name_b")
        steps.add((tier, name))
    if not steps:
        raise AssertionError(f"no steps parsed from {BASH_DRIVER.name}; the call-site convention has changed")
    return steps


def _ps1_declared_steps() -> set[tuple[str, str]]:
    return {(step.tier, step.name) for step in em.parse_declared_steps(PS1_DRIVER.read_text(encoding="utf-8"))}


def test_bash_driver_declares_exactly_the_ps1_steps() -> None:
    """Both directions, because each failure mode breaks the freshness gate.

    A step the bash driver records but the parser cannot see hard-fails the run's
    policy check. A step the parser declares but the bash driver can never record
    renders as 'not reached in this run' on every POSIX-generated artifact --
    indistinguishable from a silently dropped journey.
    """
    bash = _bash_declared_steps()
    ps1 = _ps1_declared_steps()
    assert bash == ps1, f"e2e driver step drift: bash-only {sorted(bash - ps1)}, ps1-only {sorted(ps1 - bash)}"


def test_bash_driver_mirrors_the_python_skip_code() -> None:
    """78/EX_CONFIG must mean 'not configured' in every driver (see test_smoke_lib)."""
    text = BASH_DRIVER.read_text(encoding="utf-8")
    match = re.search(r"^SKIP_EXIT_CODE=(\d+)", text, re.MULTILINE)
    assert match is not None, "run_all_e2e.sh no longer defines SKIP_EXIT_CODE"
    assert match.group(1) == "78"


def test_bash_driver_is_syntax_clean() -> None:
    """`bash -n` catches the parse errors that only surface mid-run otherwise."""
    import shutil
    import subprocess

    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash not on PATH")
    proc = subprocess.run([bash, "-n", str(BASH_DRIVER)], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr
