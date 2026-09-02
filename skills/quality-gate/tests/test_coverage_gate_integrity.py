"""Positive-control tests: prove the REAL coverage gate actually gates.

``test_render.py`` proves the generator emits the right shell *text*; ``test_gen_gate.py``'s
shared ``_project()`` fixture hardcodes ``fail_under=0`` in every synthetic ``pyproject.toml``,
so nothing in that suite could ever demonstrate the threshold does anything at all -- the exact
structural gap ``harden-quality-gate-integrity`` closes. This module runs the real, rendered
``quality-gate.sh coverage`` stage, via a real ``bash`` subprocess, against a real package with
a genuinely low or genuinely high measured coverage percentage and a meaningful (non-zero)
``fail_under``. Nothing here is mocked -- the outcome IS the point:

- a genuinely under-covered fixture fails, with coverage.py's own "Required test coverage ...
  not reached" text;
- a genuinely fully-covered fixture passes;
- the low-coverage fixture STILL fails with ``COV_FAIL_UNDER=0`` injected into the subprocess
  environment (the finding-1 evasion, tried for real);
- the low-coverage fixture STILL fails with a coverage-weakening ``PYTEST_ADDOPTS`` injected
  into the subprocess environment (the finding-3 evasion, tried for real);
- the low-coverage fixture STILL fails with ``COVERAGE_RCFILE`` pointed at a permissive
  external rc file (``fail_under=0``, a broad ``exclude_lines``) injected into the subprocess
  environment (the ``docs/plans/eval-evidence-integrity/`` review finding, tried for real).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import gen_gate
import pytest

BASH = shutil.which("bash")


def _bash_works() -> bool:
    """Return True only when bash can execute a script at a native temp path.

    Duplicated from ``test_gen_gate.py`` deliberately: WSL bash resolves on ``shutil.which``
    but cannot handle Windows-style paths, returning exit code 127, so a real probe is needed
    rather than trusting ``which`` alone. See that module for the same check.
    """
    if BASH is None:
        return False
    script: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".sh", delete=False, mode="w") as f:
            f.write("#!/usr/bin/env bash\necho ok\n")
            script = f.name
        result = subprocess.run([BASH, script], capture_output=True, text=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False
    finally:
        if script:
            Path(script).unlink(missing_ok=True)


BASH_OK = _bash_works()

pytestmark = pytest.mark.skipif(not BASH_OK, reason="bash not functional on this platform")

# Meaningful and non-zero on purpose: fail_under=0 (test_gen_gate.py's shared fixture) can
# never distinguish "the gate ran" from "the gate enforces anything". 90 sits strictly between
# the low fixture's real measured coverage (~42%) and the high fixture's (100%).
_FAIL_UNDER = 90

_DEMO_MODULE = '''"""demo package for quality-gate coverage positive controls."""


def add(a: int, b: int) -> int:
    return a + b


def subtract(a: int, b: int) -> int:
    return a - b


def multiply(a: int, b: int) -> int:
    return a * b


def divide(a: int, b: int) -> float:
    if b == 0:
        raise ValueError("cannot divide by zero")
    return a / b
'''

# Exercises only add() -- measured at ~42% branch coverage (well below _FAIL_UNDER).
_LOW_COVERAGE_TESTS = """from demo import add


def test_add() -> None:
    assert add(1, 2) == 3
"""

# Exercises every function and both branches of divide() -- 100% coverage.
_HIGH_COVERAGE_TESTS = """import pytest

from demo import add, divide, multiply, subtract


def test_add() -> None:
    assert add(1, 2) == 3


def test_subtract() -> None:
    assert subtract(3, 1) == 2


def test_multiply() -> None:
    assert multiply(2, 3) == 6


def test_divide() -> None:
    assert divide(6, 2) == 3


def test_divide_by_zero_raises() -> None:
    with pytest.raises(ValueError):
        divide(1, 0)
"""


def _coverage_fixture(root: Path, *, test_body: str) -> None:
    """Write a real Python package + tests + a pyproject.toml with a MEANINGFUL fail_under.

    ``pythonpath = ["src"]`` (pytest's own ini option, not an external ``PYTHONPATH`` the
    subprocess call would otherwise have to inject) makes the fixture self-contained: the
    rendered ``quality-gate.sh`` runs unmodified, exactly as a real project's would.
    """
    (root / "src" / "demo").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "src" / "demo" / "__init__.py").write_text(_DEMO_MODULE, encoding="utf-8")
    (root / "tests" / "test_ok.py").write_text(test_body, encoding="utf-8")
    (root / "pyproject.toml").write_text(
        '[project]\nname="demo"\nversion="0"\n'
        '[project.optional-dependencies]\ndev=["pytest-cov"]\n'
        "[tool.pytest.ini_options]\ntestpaths=['tests']\npythonpath=['src']\n"
        f'[tool.coverage.run]\nsource=["demo"]\n[tool.coverage.report]\nfail_under={_FAIL_UNDER}\n',
        encoding="utf-8",
    )


_GUARDED_VARS = ("COVERAGE_SOURCE", "COV_FAIL_UNDER", "PYTEST_ADDOPTS", "COVERAGE_RCFILE")


def _run_coverage(root: Path, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Actually execute the real, rendered ``quality-gate.sh coverage`` stage.

    A real ``bash`` subprocess running the real generated script against the real, installed
    ``pytest``/``coverage`` -- no mocking, since the outcome is the entire point.

    The three guarded vars are stripped from the inherited ambient environment before
    ``extra_env`` is applied: a "baseline" call (``extra_env=None``) must mean those vars are
    genuinely unset in the subprocess, not merely unset in ``extra_env`` -- a stray ambient
    ``PYTEST_ADDOPTS`` picked up from the calling shell would otherwise silently invalidate the
    "no override" tests' assertions that the ignored-override notices stay absent.
    """
    env = {k: v for k, v in os.environ.items() if k not in _GUARDED_VARS}
    env["PYTHON"] = "python3"
    if extra_env:
        env.update(extra_env)
    assert BASH is not None
    return subprocess.run(
        [BASH, "scripts/quality-gate.sh", "coverage"],
        cwd=str(root),
        capture_output=True,
        text=True,
        env=env,
    )


def test_low_coverage_fixture_fails_the_real_gate(tmp_path: Path) -> None:
    """A genuinely under-covered package's real, rendered gate actually fails."""
    _coverage_fixture(tmp_path, test_body=_LOW_COVERAGE_TESTS)
    assert gen_gate.main(["--root", str(tmp_path)]) == 0
    result = _run_coverage(tmp_path)
    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    assert "Required test coverage" in combined
    assert "not reached" in combined
    # Baseline: no env override at all. The three ignored-override notices are guarded by
    # `if [ -n "${VAR:-}" ]; ...` in the rendered script, so with the var genuinely unset they
    # must never print. Nothing previously asserted this ABSENCE, so a guard rewritten to fire
    # unconditionally (regardless of the var's state) would have gone undetected here.
    assert "COVERAGE_SOURCE is ignored" not in combined
    assert "COV_FAIL_UNDER is ignored" not in combined
    assert "PYTEST_ADDOPTS is ignored" not in combined
    assert "COVERAGE_RCFILE is ignored" not in combined


def test_high_coverage_fixture_passes_the_real_gate(tmp_path: Path) -> None:
    """The same fixture shape, fully exercised, passes -- the gate is not unconditionally
    red; it responds to real coverage in both directions."""
    _coverage_fixture(tmp_path, test_body=_HIGH_COVERAGE_TESTS)
    assert gen_gate.main(["--root", str(tmp_path)]) == 0
    result = _run_coverage(tmp_path)
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "Required test coverage" in combined
    assert "not reached" not in combined
    # Same baseline-absence guard as the low-coverage case above, on the passing path too --
    # a gate that happens to pass must still be silent about overrides nobody set.
    assert "COVERAGE_SOURCE is ignored" not in combined
    assert "COV_FAIL_UNDER is ignored" not in combined
    assert "PYTEST_ADDOPTS is ignored" not in combined
    assert "COVERAGE_RCFILE is ignored" not in combined


def test_cov_fail_under_zero_does_not_evade_the_low_coverage_gate(tmp_path: Path) -> None:
    """Finding 1, tried for real and confirmed closed.

    ``COV_FAIL_UNDER`` is no longer referenced anywhere in the generated script -- the
    threshold is a generation-time literal -- so setting it in the subprocess environment has
    NO effect on the outcome: the low-coverage fixture still fails, against the real configured
    threshold, not a weakened one.
    """
    _coverage_fixture(tmp_path, test_body=_LOW_COVERAGE_TESTS)
    assert gen_gate.main(["--root", str(tmp_path)]) == 0
    result = _run_coverage(tmp_path, extra_env={"COV_FAIL_UNDER": "0"})
    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    assert f"Required test coverage of {_FAIL_UNDER}%" in combined
    assert "COV_FAIL_UNDER is ignored" in result.stderr


def test_pytest_addopts_does_not_evade_the_low_coverage_gate(tmp_path: Path) -> None:
    """Finding 3, tried for real and confirmed closed.

    ``PYTEST_ADDOPTS=--no-cov`` would normally suppress pytest-cov entirely (and with it, the
    ``--cov-fail-under`` check); the generated gate unsets it before invoking pytest, so the
    coverage step still runs and still fails against the low-coverage fixture.
    """
    _coverage_fixture(tmp_path, test_body=_LOW_COVERAGE_TESTS)
    assert gen_gate.main(["--root", str(tmp_path)]) == 0
    result = _run_coverage(tmp_path, extra_env={"PYTEST_ADDOPTS": "--no-cov"})
    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    assert "Required test coverage" in combined
    assert "PYTEST_ADDOPTS is ignored" in result.stderr


def test_coverage_source_override_does_not_change_what_is_measured(tmp_path: Path) -> None:
    """Finding 2 (the single-source case), tried for real and confirmed closed.

    Pointing ``COVERAGE_SOURCE`` at a trivially-covered path must not change the reported
    percentage or the pass/fail outcome: the source is a generation-time literal.
    """
    _coverage_fixture(tmp_path, test_body=_LOW_COVERAGE_TESTS)
    assert gen_gate.main(["--root", str(tmp_path)]) == 0
    baseline = _run_coverage(tmp_path)
    overridden = _run_coverage(tmp_path, extra_env={"COVERAGE_SOURCE": "nonexistent_pkg"})
    assert baseline.returncode == overridden.returncode != 0
    assert "COVERAGE_SOURCE is ignored" in overridden.stderr
    # The reported source in the table is still "demo", never the overridden value.
    assert "src/demo/__init__.py" in overridden.stdout
    assert "nonexistent_pkg" not in overridden.stdout


def test_coverage_rcfile_override_does_not_evade_the_low_coverage_gate(tmp_path: Path) -> None:
    """The ``COVERAGE_RCFILE`` evasion, tried for real and confirmed closed.

    A rogue rc file pointed at by ``COVERAGE_RCFILE`` -- the kind an accidental environment
    leak (or an attacker controlling the CI environment) could supply -- sets a permissive
    ``fail_under = 0`` and an ``exclude_lines`` broad enough to exclude every line in the demo
    package. Without the fix this would silently drive measured coverage to 100% and pass the
    low-coverage fixture; with the explicit ``--cov-config=pyproject.toml`` literal (which
    coverage.py prioritises over the env var) plus the warn-then-unset guard, the rogue file is
    never consulted at all -- the gate still fails against the real, generation-time threshold.
    """
    _coverage_fixture(tmp_path, test_body=_LOW_COVERAGE_TESTS)
    assert gen_gate.main(["--root", str(tmp_path)]) == 0
    rogue_rc = tmp_path.parent / "rogue.coveragerc"
    rogue_rc.write_text(
        "[report]\nfail_under = 0\nexclude_lines =\n    .*\n",
        encoding="utf-8",
    )
    result = _run_coverage(tmp_path, extra_env={"COVERAGE_RCFILE": str(rogue_rc)})
    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    assert f"Required test coverage of {_FAIL_UNDER}%" in combined
    assert "COVERAGE_RCFILE is ignored" in result.stderr
