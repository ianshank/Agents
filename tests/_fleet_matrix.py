"""Fleet-matrix census (eval-evidence Phase 9 / ADR 0032 §6).

Two mechanisms, never a third:

* **Derived** where a registry exists — ``CALIBRATOR_FACTORIES`` in agent-core
  (``CalibratorRegistry`` is a container, not a factory, and is excluded) and
  ``SPECIMENS.register(...)`` in flow-corpus. Derivation is AST-only so this
  module does not import sibling packages (the root suite does not always have
  them on ``sys.path``).
* **Checked declaration** otherwise — each name is a subset of that package's
  frozen public-surface (or backwards-compat) baseline. A declared name that
  is not an exported public name fails; a surface change makes a stale
  declaration fail the other direction only when we claimed that name.

This is scaffolding, not a second ``MATRIX_KIND`` grid. Package test suites
do not have to grow ``test_m*`` rows to land this module.
"""

from __future__ import annotations

import ast
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class FleetPackage:
    """One sibling (or staging) package the fleet census covers."""

    name: str
    root: str
    kind: str
    baseline_relpath: str
    derivation: str
    declared: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    source_relpath: str = ""
    assign_name: str = ""


#: ``CalibratorRegistry`` is the false friend: it is exported, it sounds like a
#: registry census, and it is *not* a factory in ``CALIBRATOR_FACTORIES``.
FLEET_PACKAGES: tuple[FleetPackage, ...] = (
    FleetPackage(
        name="agent-core",
        root="agent-core",
        kind="calibrator",
        baseline_relpath="agent-core/tests/public_surface_baseline.json",
        derivation="assign",
        exclude=("CalibratorRegistry",),
        source_relpath="agent-core/agent_core/recalibration.py",
        assign_name="CALIBRATOR_FACTORIES",
    ),
    FleetPackage(
        name="flow-corpus",
        root="flow-corpus",
        kind="specimen",
        baseline_relpath="flow-corpus/tests/public_surface_baseline.json",
        derivation="register",
        source_relpath="flow-corpus/flow_corpus/specimens/__init__.py",
        assign_name="SPECIMENS",
    ),
    FleetPackage(
        name="behavioral-regression",
        root="behavioral-regression",
        kind="detector",
        baseline_relpath="behavioral-regression/tests/public_surface_baseline.json",
        derivation="hand",
        declared=("RegressionDetector", "ShipDecision", "SyntheticJudge", "PairedResponseGenerator"),
    ),
    FleetPackage(
        name="flow-protocol",
        root="flow-protocol",
        kind="protocol",
        baseline_relpath="flow-protocol/tests/public_surface_baseline.json",
        derivation="hand",
        declared=("ConfidenceChannel", "FlowResult", "OracleResult", "OracleTier"),
    ),
    FleetPackage(
        name="claude-foundation",
        root="claude-foundation",
        kind="plugin",
        baseline_relpath="claude-foundation/tests/backwards_compat_baseline.json",
        derivation="hand",
        declared=(
            "explorer",
            "peer-reviewer",
            "spec-guardian",
            "test-runner",
            "post_edit_verify.py",
            "pre_tool_guard.py",
            "session_logger.py",
            "c4-docs",
            "code-review",
            "plan",
            "test-first",
        ),
    ),
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _dict_target_matches(node: ast.AST, assign_name: str) -> ast.Dict | None:
    """Return the dict literal of ``NAME = {...}`` or ``NAME: T = {...}``."""
    if (
        isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Dict)
        and any(isinstance(t, ast.Name) and t.id == assign_name for t in node.targets)
    ):
        return node.value
    if (
        isinstance(node, ast.AnnAssign)
        and isinstance(node.value, ast.Dict)
        and isinstance(node.target, ast.Name)
        and node.target.id == assign_name
    ):
        return node.value
    return None


def dict_literal_keys(source: str, assign_name: str) -> frozenset[str]:
    """String keys of ``ASSIGN = { "k": ... }`` or an annotated form of the same."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        value = _dict_target_matches(node, assign_name)
        if value is None:
            continue
        keys: list[str] = []
        for key in value.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                keys.append(key.value)
        return frozenset(keys)
    return frozenset()


def register_call_names(source: str, registry_name: str) -> frozenset[str]:
    """String first-args of ``REGISTRY.register("name", ...)``."""
    tree = ast.parse(source)
    names: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        if not (
            isinstance(func, ast.Attribute)
            and func.attr == "register"
            and isinstance(func.value, ast.Name)
            and func.value.id == registry_name
        ):
            continue
        arg0 = node.args[0]
        if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
            names.append(arg0.value)
    return frozenset(names)


def baseline_names(payload: Mapping[str, object]) -> frozenset[str]:
    """Every exported name in a public-surface or backwards-compat baseline."""
    names: set[str] = set()
    surface = payload.get("surface")
    if isinstance(surface, dict):
        for values in surface.values():
            if isinstance(values, list):
                names.update(str(v) for v in values)
    components = payload.get("components")
    if isinstance(components, dict):
        for values in components.values():
            if isinstance(values, list):
                names.update(str(v) for v in values)
    return frozenset(names)


def load_baseline(path: Path) -> frozenset[str]:
    data = json.loads(_read(path))
    if not isinstance(data, dict):
        return frozenset()
    return baseline_names(data)


def census_for(package: FleetPackage, *, root: Path = _REPO_ROOT) -> frozenset[str]:
    """Component names this package contributes to the fleet census."""
    if package.derivation == "assign":
        src = _read(root / package.source_relpath)
        return dict_literal_keys(src, package.assign_name) - frozenset(package.exclude)
    if package.derivation == "register":
        src = _read(root / package.source_relpath)
        return register_call_names(src, package.assign_name)
    return frozenset(package.declared)


def fleet_problems(*, root: Path = _REPO_ROOT, packages: tuple[FleetPackage, ...] = FLEET_PACKAGES) -> list[str]:
    """Both-directions checks: derived/declared names must sit on the frozen baseline."""
    problems: list[str] = []
    if not packages:
        return ["fleet census is empty"]
    for package in packages:
        baseline_path = root / package.baseline_relpath
        if not baseline_path.is_file():
            problems.append(f"{package.name}: baseline missing at {package.baseline_relpath}")
            continue
        exported = load_baseline(baseline_path)
        if not exported:
            problems.append(f"{package.name}: baseline exported no names")
            continue
        names = census_for(package, root=root)
        if not names:
            problems.append(f"{package.name}: fleet census is empty")
            continue
        if package.derivation == "hand":
            for name in sorted(names):
                if name not in exported:
                    problems.append(f"{package.name}: {name!r} is not in {package.baseline_relpath}")
            continue
        if package.assign_name and package.assign_name not in exported:
            problems.append(
                f"{package.name}: derived registry {package.assign_name!r} is not in {package.baseline_relpath}"
            )
        if "CalibratorRegistry" in names:
            problems.append(f"{package.name}: CalibratorRegistry must not be derived from CALIBRATOR_FACTORIES")
    return problems
