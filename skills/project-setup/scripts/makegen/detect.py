"""Detect a Python project's toolchain deterministically from its files.

Every fact is derived from an observable input (``pyproject.toml`` tables, marker files,
directory layout). No network, no heuristics that vary between runs: the same tree always
yields the same :class:`ProjectFacts`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .model import ProjectFacts

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - 3.10 path, exercised in the 3.10 CI matrix
    import tomli as tomllib  # type: ignore[no-redef]


def _load_pyproject(root: Path) -> dict[str, Any]:
    """Parse ``pyproject.toml`` if present; return {} on absence or parse error."""
    path = root / "pyproject.toml"
    if not path.is_file():
        return {}
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _table(data: dict[str, Any], *keys: str) -> dict[str, Any]:
    """Return the nested table at ``keys`` if every level is a dict, else {}."""
    cur: Any = data
    for key in keys:
        if not isinstance(cur, dict):
            return {}
        cur = cur.get(key)
    return cur if isinstance(cur, dict) else {}


def _has_table(data: dict[str, Any], *keys: str) -> bool:
    """True if the nested table at ``keys`` is *present* (even when empty).

    Presence, not truthiness: ``[tool.ruff]`` with no keys parses to ``{}`` yet still means
    "ruff is configured", so a plain ``bool(_table(...))`` would wrongly read it as absent.
    """
    cur: Any = data
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return False
        cur = cur[key]
    return isinstance(cur, dict)


def _mentions(data: dict[str, Any], needle: str) -> bool:
    """True if any declared dependency mentions ``needle`` (e.g. ``pytest-cov``).

    Scans PEP 621 ``[project].dependencies`` and ``optional-dependencies`` plus PEP 735
    ``[dependency-groups]`` (only string requirements — ``include-group`` dicts are skipped).
    """
    project = _table(data, "project")
    deps: list[Any] = list(project.get("dependencies", []) or [])
    for group in (project.get("optional-dependencies", {}) or {}).values():
        deps.extend(group or [])
    for group in (_table(data, "dependency-groups") or {}).values():
        deps.extend(group or [])
    return any(isinstance(dep, str) and needle in dep for dep in deps)


def _coerce_threshold(value: Any) -> int:
    """Coerce a coverage ``fail_under`` value to an int, tolerating strings like ``"90"``.

    Falls back to 0 (no enforcement) on anything unparseable — a percent sign, a list, None —
    rather than silently dropping a legitimately string-typed threshold.
    """
    if value is None:
        return 0
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return 0


def _detect_package_manager(root: Path, data: dict[str, Any]) -> tuple[str, str]:
    """Return ``(manager, install_command)`` from lockfiles / tool tables / layout."""
    if _has_table(data, "tool", "poetry") or (root / "poetry.lock").is_file():
        return "poetry", "poetry install"
    if _has_table(data, "tool", "pdm") or (root / "pdm.lock").is_file():
        return "pdm", "pdm install"
    if (root / "uv.lock").is_file() or _has_table(data, "tool", "uv"):
        return "uv", "uv sync"
    if _has_table(data, "tool", "hatch"):
        return "hatch", "hatch env create"
    project = _table(data, "project")
    if "dev" in (project.get("optional-dependencies", {}) or {}):
        return "pip", '$(PIP) install -e ".[dev]"'
    if "build-system" in data or _has_table(data, "project"):
        return "pip", "$(PIP) install -e ."
    if (root / "requirements.txt").is_file():
        return "pip", "$(PIP) install -r requirements.txt"
    return "pip", "$(PIP) install -e ."


def _detect_type_checker(root: Path, data: dict[str, Any], src_layout: bool) -> tuple[str | None, str]:
    """Prefer mypy, then pyright; return ``(checker, paths_to_check)``."""
    paths = "src" if src_layout else "."
    if _has_table(data, "tool", "mypy") or (root / "mypy.ini").is_file():
        return "mypy", paths
    if (root / "pyrightconfig.json").is_file() or _has_table(data, "tool", "pyright"):
        return "pyright", paths
    return None, paths


def _guess_package(data: dict[str, Any], root: Path, src_layout: bool) -> str:
    """Best-effort coverage source: first src package, else normalized project name, else '.'."""
    base = root / "src"
    if src_layout and base.is_dir():
        pkgs = sorted(p.name for p in base.iterdir() if (p / "__init__.py").is_file())
        if pkgs:
            return pkgs[0]
    name = _table(data, "project").get("name")
    if isinstance(name, str) and name:
        return name.replace("-", "_")
    return "."


def _detect_coverage(data: dict[str, Any], root: Path, src_layout: bool) -> tuple[str, int]:
    """Return ``(coverage_source, fail_under)`` from ``[tool.coverage]`` with safe fallbacks."""
    run = _table(data, "tool", "coverage", "run")
    report = _table(data, "tool", "coverage", "report")
    source = run.get("source")
    src = ""
    if isinstance(source, list) and source:
        src = str(source[0])
    elif isinstance(source, str):
        src = source
    if not src:
        src = _guess_package(data, root, src_layout)
    return src or ".", _coerce_threshold(report.get("fail_under"))


def detect(root: Path | str) -> ProjectFacts:
    """Inspect a project tree and return the deterministic facts the renderer needs."""
    root = Path(root)
    data = _load_pyproject(root)
    src_layout = (root / "src").is_dir()
    manager, install_cmd = _detect_package_manager(root, data)
    checker, tc_paths = _detect_type_checker(root, data, src_layout)
    cov_source, cov_fail_under = _detect_coverage(data, root, src_layout)
    has_ruff = _has_table(data, "tool", "ruff") or (root / "ruff.toml").is_file() or (root / ".ruff.toml").is_file()
    has_pytest = _has_table(data, "tool", "pytest") or (root / "pytest.ini").is_file() or (root / "tests").is_dir()
    return ProjectFacts(
        package_manager=manager,
        install_cmd=install_cmd,
        has_ruff=has_ruff,
        type_checker=checker,
        typecheck_paths=tc_paths,
        has_pytest=has_pytest,
        # Precise signal: `pytest --cov` needs the pytest-cov plugin, so require it to be a
        # declared dependency. A bare [tool.coverage] table (standalone coverage.py) is NOT
        # enough — emitting `pytest --cov` there would fabricate a command that fails.
        has_pytest_cov=_mentions(data, "pytest-cov"),
        coverage_source=cov_source,
        cov_fail_under=cov_fail_under,
        src_layout=src_layout,
        has_build_backend="build-system" in data,
        has_quality_gate_script=(root / "scripts" / "quality-gate.sh").is_file(),
        has_deploy_script=(root / "scripts" / "deploy.sh").is_file(),
    )
