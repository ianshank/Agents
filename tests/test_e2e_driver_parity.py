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


def _bash_works() -> tuple[str | None, bool]:
    """The bash on PATH, and whether it can actually run a script at a native path.

    On Windows ``shutil.which("bash")`` finds the WSL shim, which answers
    ``bash -c`` but cannot open a Windows-native path (exit 127) — so a
    ``which(...) is not None`` gate turns into a false failure rather than a skip.
    Probing with a real temp script is the repo-wide convention (AGENTS.md; the
    quality-gate and deploy skill suites carry the same probe).
    """
    import shutil
    import subprocess
    import tempfile

    bash = shutil.which("bash")
    if bash is None:
        return None, False
    script: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".sh", delete=False, mode="w") as handle:
            handle.write("#!/usr/bin/env bash\necho ok\n")
            script = handle.name
        proc = subprocess.run([bash, script], capture_output=True, text=True, check=False)
        return bash, proc.returncode == 0
    except OSError:
        return bash, False
    finally:
        if script is not None:
            Path(script).unlink(missing_ok=True)


def test_bash_driver_is_syntax_clean() -> None:
    """`bash -n` catches the parse errors that only surface mid-run otherwise."""
    import subprocess

    bash, works = _bash_works()
    if not works:
        pytest.skip("no bash that can read a native path (WSL shim or bash absent)")
    assert bash is not None
    proc = subprocess.run([bash, "-n", str(BASH_DRIVER)], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr


def test_step_helpers_capture_the_real_exit_code() -> None:
    """`cmd || true` then `rc=$?` reads the status of `true`, so rc is always 0.

    Under that idiom every failing step recorded PASS: `invoke_cmd_step` matched the
    0-is-a-pass-code branch unconditionally, and `invoke_pytest_step` passed whenever
    a junit file existed at all — including a run whose tests failed. The report is
    the artifact the nightly freshness job publishes, so a false PASS there is worse
    than no report. `run_py` already uses the correct form.
    """
    text = BASH_DRIVER.read_text(encoding="utf-8")
    assert not re.search(r"\|\|\s*true\s*\n\s*rc=\$\?", text), (
        "a step helper is discarding run_py's exit code; use `|| rc=$?`"
    )
    # Derived, not a magic count: every call site must capture, however many there are.
    # Backslash continuations are joined first — the pre-flight call puts its `|| rc=$?`
    # on the following physical line, and a line-at-a-time read would misreport it.
    joined = re.sub(r"\\\n\s*", " ", text)
    call_sites = [ln.strip() for ln in joined.splitlines() if re.match(r"\s*run_py\s", ln)]
    assert call_sites, "run_py is no longer called; this guard has gone stale"
    uncaptured = [ln for ln in call_sites if "|| rc=$?" not in ln]
    assert not uncaptured, f"run_py call sites that drop the exit code: {uncaptured}"
