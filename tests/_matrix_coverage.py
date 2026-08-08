"""Library behind the matrix completeness guard and the generated coverage artifact.

Underscore-prefixed so pytest does not collect it (the precedent is
``tests/_trajectory_helpers.py`` / ``tests/_sut.py``); the tests live in
``tests/test_matrix_coverage.py``, which also carries the ``--check`` / ``--update``
CLI for ``docs/matrix-coverage.md``.

Three moving parts, single-sourced here so ``scripts/validations/F_053.py`` can import
them instead of restating them (the F-052 no-restatement principle):

* **The census** — which components exist, per registry kind. Read in a FRESH
  SUBPROCESS (the registries are process-global and two test modules register doubles
  into them, so an in-process read is collection-order-dependent), with a richer
  payload than the surface guard's flat union: ``{kind: {"names": [...],
  "aliases": {alias: canonical}}}``. Registries are discovered dynamically
  (``isinstance(obj, Registry)`` over ``eval_harness.plugins``, keyed by ``.kind``),
  so a future sixth registry is censused automatically and fails the policy check
  with an actionable message until it has a ``REQUIRED_DIMS`` row.
* **The cell map** — which matrix rows exist, read by AST over every
  ``tests/test_matrix_*.py``. Matrix classes declare ``MATRIX_KIND`` and
  ``MATRIX_COMPONENTS`` as literals (a literal cross-checked against the live census
  is a *checked declaration* — a stale tuple fails loudly; the banned thing is a
  literal that claims completeness unchecked, like the old hardcoded M7 lists).
  ``MATRIX_COMPONENTS`` may also name a module-level literal tuple in the same file
  (single-file constant folding only — cross-file names are not resolved).
  Dimensions come from ``test_m([1-8])_`` method-name prefixes; per-cell counts are
  static method counts, never runtime-parametrized case counts.
* **The policy** — ``REQUIRED_DIMS`` / ``EXTRA_SUITES`` / ``WAIVED`` /
  ``FROZEN_ALIAS_MAP`` / ``FOLLOW_ON``, normative content of ADR 0032.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _TESTS_DIR.parent
_DOC_PATH = _REPO_ROOT / "docs" / "matrix-coverage.md"
_PROBE_TIMEOUT_SECONDS = 30

#: Dimension floors per registry kind (ADR 0032). M4 and M7 are global-dynamic
#: (``TestM4Interface`` parametrizes the live registries; ``TestM7Registry``
#: parametrizes the committed baseline), and M8 is per-kind (every kind appears in at
#: least one PIPELINES config), so none of the three appears in a floor set.
#: Rule for future kinds: a dim is floor for a kind iff meaningful for every member
#: absent a documented waiver, and waivers stay a small minority; subset-meaningful
#: dims are extra rows — welcome, never required.
REQUIRED_DIMS: dict[str, frozenset[int]] = {
    "scorer": frozenset({1, 2, 3, 5, 6}),
    "judge": frozenset({1, 2, 3, 6}),  # M5 excluded: verdict determinism is the provider's
    "dataset": frozenset({1, 2, 3, 6}),
    "target": frozenset({1, 2, 3, 6}),  # M6 required: the model target is the riskiest surface
    "sink": frozenset({1, 2, 6}),  # M2 = empty-run emit; M6 = degrade/error path
}

#: Non-registry matrix rows enforced with the same machinery: gating and the engine
#: pipelines. A class claims one by setting ``MATRIX_KIND`` to the suite name.
EXTRA_SUITES: dict[str, frozenset[int]] = {
    "gating": frozenset({1, 2, 6}),
    "engine": frozenset({8}),
}

#: ``(kind, component, dim) -> reason``. Self-guarded both ways: a waiver naming an
#: unregistered component fails ("stale waiver"), and a waiver for a cell that now has
#: tests fails ("waiver no longer needed").
WAIVED: dict[tuple[str, str, int], str] = {
    ("target", "echo", 6): "no failure modes by design (pure dict access)",
    ("dataset", "inline", 6): "config-embedded items have no I/O failure path; a malformed record fails loudly at load",
    ("sink", "console", 6): "prints to stdout; no failure path to exercise",
}

#: The directed alias→canonical pairing per kind, frozen by exact equality. The
#: committed registry baseline stores names and aliases merged flat, and
#: ``Registry._aliases`` assignment has no duplicate guard — a silently repointed
#: alias still *resolves*, so only an exact-equality map catches it. A new alias
#: fails here until it is added; a dropped or repointed one fails immediately.
FROZEN_ALIAS_MAP: dict[str, dict[str, str]] = {
    "dataset": {"csv_file": "csv", "parquet_file": "parquet"},
    "judge": {"claude": "anthropic", "deterministic": "mock", "phoenix-evals": "phoenix_evals"},
    "scorer": {
        "composite": "weighted",
        "ensemble": "weighted",
        "exact": "exact_match",
        "judge": "llm_judge",
        "llm-judge": "llm_judge",
        "regex": "regex_match",
        "schema_keys": "json_keys",
        "trajectory-any-order": "trajectory_any_order",
        "trajectory-exact": "trajectory_exact",
        "trajectory-in-order": "trajectory_in_order",
        "trajectory-loop-detection": "trajectory_loop_detection",
        "trajectory-precision-recall": "trajectory_precision_recall",
        "trajectory-recovery": "trajectory_recovery",
        "trajectory-step-efficiency": "trajectory_step_efficiency",
    },
    "sink": {"html": "html_file", "json": "json_file"},
    "target": {"llm": "model", "python": "callable"},
}


@dataclass(frozen=True)
class FollowOn:
    """A recorded matrix obligation owed by a queued OpenSpec change.

    Rendered in the artifact so the doc is the roadmap; hygiene mirrors waivers — a
    row whose component now exists in the census fails as "satisfied: remove the row".
    ``component`` is None for obligations that add no registry component (those cannot
    be auto-caught by the census and are listed for the reader, not the checker).
    """

    change_id: str
    kind: str
    component: str | None
    note: str


FOLLOW_ON: tuple[FollowOn, ...] = (
    FollowOn(
        "add-repeat-reliability-metrics",
        "gating",
        None,
        "gate rules for pass_at_k / pass_power_k inherit the enforced gating floor; "
        "ReliabilityAggregator needs M5; repetitions>1 needs an M8 pipeline. No new "
        "registry, so the census cannot auto-catch this change.",
    ),
    FollowOn(
        "add-stateful-outcome-evaluation",
        "state_adapter",
        None,
        "STATE_ADAPTERS is a sixth registry: the census discovers it automatically and "
        "this guard fails until it has a REQUIRED_DIMS row plus rows for the four local "
        "adapters and the two state scorers (whose registered names must also land in "
        "both READMEs for the registry-drift guard).",
    ),
    FollowOn(
        "extend-judge-calibration",
        "judge",
        None,
        "bias-probe math lands in agent_core (airgap-preserving); the agent-core matrix "
        "suite gains probe rows in the fleet phase. Not auto-caught by this census.",
    ),
)

#: Files the cell map is read from (glob, so a future split of the matrix suite into
#: several files keeps working without touching the extractor).
MATRIX_FILE_GLOB = "test_matrix_*.py"

_DIM_METHOD_RE = re.compile(r"^test_m([1-8])_")
_DIM_TITLES: dict[int, str] = {
    1: "Correctness",
    2: "Edge Cases",
    3: "Type Safety",
    4: "Interface",
    5: "Determinism",
    6: "Error Handling",
    7: "Registry",
    8: "Composability",
}

# --------------------------------------------------------------------------- census

# Mirrors tests/conftest.py's sys.path setup because a bare `python -c` child gets no
# conftest handling; registries are discovered by isinstance over the plugins module
# namespace, keyed by each registry's own `.kind`. `_aliases` is read directly —
# there is no public accessor, and the alias map is exactly what FROZEN_ALIAS_MAP
# freezes. See tests/test_plugin_registry_surface.py for the failure-mode rationale
# this probe copies (timeout, non-zero exit, garbled stdout).
_PROBE = """\
import sys
from pathlib import Path

_root = Path.cwd()
for _p in (str(_root), str(_root / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import json

from eval_harness import plugins
from eval_harness.core.registry import Registry

plugins.load_builtin_plugins()
registries = {obj.kind: obj for obj in vars(plugins).values() if isinstance(obj, Registry)}
census = {
    kind: {"names": sorted(reg.names()), "aliases": dict(sorted(reg._aliases.items()))}
    for kind, reg in registries.items()
}
print(json.dumps(census))
"""


def _run_probe() -> subprocess.CompletedProcess[str]:
    """One fresh-interpreter census run. Split out so tests can monkeypatch it."""
    return subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
        timeout=_PROBE_TIMEOUT_SECONDS,
    )


def _parse_census(raw: object, *, source: str) -> dict[str, dict[str, object]]:
    """Shape-validate ``{kind: {names: [...], aliases: {...}}}`` with source-tagged errors."""
    if not isinstance(raw, dict):
        raise TypeError(f"{source}: top level must be a JSON object")
    shaped: dict[str, dict[str, object]] = {}
    for kind, payload in raw.items():
        if not isinstance(payload, dict) or set(payload) != {"names", "aliases"}:
            raise TypeError(f"{source}: {kind!r} must be an object with 'names' and 'aliases'")
        names = payload["names"]
        aliases = payload["aliases"]
        if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
            raise TypeError(f"{source}: {kind!r} names must be a list of strings")
        if len(set(names)) != len(names):
            raise ValueError(f"{source}: {kind!r} has duplicate names")
        if not isinstance(aliases, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in aliases.items()
        ):
            raise TypeError(f"{source}: {kind!r} aliases must be a string->string object")
        shaped[str(kind)] = {"names": list(names), "aliases": dict(aliases)}
    return shaped


@lru_cache(maxsize=1)
def registry_census() -> dict[str, dict[str, object]]:
    """The live component census, one cached subprocess per process.

    The suite runs up to six times per PR (two pytest passes per Python, three
    Pythons) — the cache keeps that to one probe per pytest process, shared by the
    policy tests, the alias freeze and the freshness test.
    """
    try:
        completed = _run_probe()
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"matrix census probe did not finish within {_PROBE_TIMEOUT_SECONDS}s") from exc
    if completed.returncode != 0:
        raise RuntimeError(
            f"matrix census probe failed (exit {completed.returncode})\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"matrix census probe output: not valid JSON ({exc})\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        ) from exc
    return _parse_census(data, source="census probe")


def census_names(census: Mapping[str, Mapping[str, object]], kind: str) -> list[str]:
    names = census[kind]["names"]
    assert isinstance(names, list)
    return names


def census_aliases(census: Mapping[str, Mapping[str, object]], kind: str) -> dict[str, str]:
    aliases = census[kind]["aliases"]
    assert isinstance(aliases, dict)
    return aliases


# --------------------------------------------------------------------------- cell map


@dataclass(frozen=True)
class MatrixClass:
    """One matrix test class, as read from the AST."""

    module: str
    name: str
    kind: str | None
    components: tuple[str, ...]
    registry_marker: bool
    #: dim -> number of test methods carrying that dim prefix (static count).
    dim_counts: dict[int, int]

    @property
    def dims(self) -> frozenset[int]:
        return frozenset(self.dim_counts)


def matrix_files(tests_dir: Path = _TESTS_DIR) -> list[Path]:
    return sorted(tests_dir.glob(MATRIX_FILE_GLOB))


def _module_literal_tuples(tree: ast.Module) -> dict[str, tuple[str, ...]]:
    """Module-level ``NAME = ("a", "b", ...)`` string-tuple assignments (same file only)."""
    found: dict[str, tuple[str, ...]] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        strings = _string_tuple(node.value)
        if isinstance(target, ast.Name) and strings is not None:
            found[target.id] = strings
    return found


def _string_tuple(node: ast.expr) -> tuple[str, ...] | None:
    if not isinstance(node, (ast.Tuple, ast.List)):
        return None
    values: list[str] = []
    for el in node.elts:
        if not (isinstance(el, ast.Constant) and isinstance(el.value, str)):
            return None
        values.append(el.value)
    return tuple(values)


def extract_matrix_classes(paths: Iterable[Path]) -> list[MatrixClass]:
    classes: list[MatrixClass] = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        module_tuples = _module_literal_tuples(tree)
        for node in tree.body:
            if not isinstance(node, ast.ClassDef) or not node.name.startswith("Test"):
                continue
            kind: str | None = None
            components: tuple[str, ...] = ()
            registry_marker = False
            dim_counts: dict[int, int] = {}
            for stmt in node.body:
                if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                    target = stmt.targets[0]
                    if not isinstance(target, ast.Name):
                        continue
                    if target.id == "MATRIX_KIND":
                        if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                            kind = stmt.value.value
                    elif target.id == "MATRIX_COMPONENTS":
                        strings = _string_tuple(stmt.value)
                        if strings is None and isinstance(stmt.value, ast.Name):
                            strings = module_tuples.get(stmt.value.id)
                        components = strings or ()
                    elif target.id == "MATRIX_REGISTRY":
                        registry_marker = bool(isinstance(stmt.value, ast.Constant) and stmt.value.value is True)
                elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    match = _DIM_METHOD_RE.match(stmt.name)
                    if match:
                        dim = int(match.group(1))
                        dim_counts[dim] = dim_counts.get(dim, 0) + 1
            classes.append(
                MatrixClass(
                    module=path.name,
                    name=node.name,
                    kind=kind,
                    components=components,
                    registry_marker=registry_marker,
                    dim_counts=dim_counts,
                )
            )
    return classes


def literal_parametrize_violations(paths: Iterable[Path]) -> list[str]:
    """Designated registry classes must never parametrize over constant literals.

    Scope: classes named ``Test*Registry`` or carrying ``MATRIX_REGISTRY = True``.
    A violation is any ``parametrize`` call whose argvalues expression consists
    entirely of constant literals at any nesting — today's defect was string lists,
    but a tuple-of-tuples restatement would be the same defect in a different shape.
    """
    violations: list[str] = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            designated = node.name.startswith("Test") and node.name.endswith("Registry")
            for stmt in node.body:
                if (
                    isinstance(stmt, ast.Assign)
                    and len(stmt.targets) == 1
                    and isinstance(stmt.targets[0], ast.Name)
                    and stmt.targets[0].id == "MATRIX_REGISTRY"
                    and isinstance(stmt.value, ast.Constant)
                    and stmt.value.value is True
                ):
                    designated = True
            if not designated:
                continue
            for call in ast.walk(node):
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "parametrize"
                    and len(call.args) >= 2
                    and _is_all_literal(call.args[1])
                ):
                    violations.append(
                        f"{path.name}::{node.name}: parametrize over a constant literal "
                        f"(line {call.args[1].lineno}) — derive from the census/baseline instead"
                    )
    return violations


def _is_all_literal(node: ast.expr) -> bool:
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return all(_is_all_literal(el) for el in node.elts)
    return False


# --------------------------------------------------------------------------- policy


def _dims_label(dims: Iterable[int]) -> list[str]:
    return sorted(f"M{d}" for d in dims)


def _collect_cells(
    census: Mapping[str, Mapping[str, object]],
    classes: Iterable[MatrixClass],
    problems: list[str],
) -> tuple[dict[tuple[str, str], set[int]], dict[str, set[int]]]:
    """Cell union per (kind, component) and extras union per suite, with class-side checks."""
    cells: dict[tuple[str, str], set[int]] = {}
    extras: dict[str, set[int]] = {}
    for cls in classes:
        if cls.kind is None:
            if cls.dim_counts and not cls.registry_marker:
                problems.append(
                    f"{cls.module}::{cls.name}: has test_m*_ methods but no MATRIX_KIND — "
                    "declare the kind (or MATRIX_REGISTRY = True for a registry class)"
                )
            continue
        if cls.kind in EXTRA_SUITES:
            extras.setdefault(cls.kind, set()).update(cls.dims)
            continue
        if cls.kind not in REQUIRED_DIMS:
            problems.append(
                f"{cls.module}::{cls.name}: unknown MATRIX_KIND {cls.kind!r} — "
                "add a REQUIRED_DIMS row in tests/_matrix_coverage.py (and amend ADR 0032)"
            )
            continue
        if not cls.components:
            problems.append(f"{cls.module}::{cls.name}: MATRIX_KIND set but MATRIX_COMPONENTS is empty")
            continue
        known = set(census_names(census, cls.kind)) if cls.kind in census else set()
        for component in cls.components:
            if component not in known:
                problems.append(
                    f"{cls.module}::{cls.name}: declares unregistered {cls.kind} {component!r} (stale declaration?)"
                )
                continue
            cells.setdefault((cls.kind, component), set()).update(cls.dims)
    return cells, extras


def _census_floor_problems(
    census: Mapping[str, Mapping[str, object]],
    cells: Mapping[tuple[str, str], set[int]],
    problems: list[str],
) -> None:
    """Every kind has a policy row; every registered component meets its floor."""
    for kind in sorted(census):
        if kind not in REQUIRED_DIMS:
            problems.append(
                f"registry kind {kind!r} has no REQUIRED_DIMS policy row — add one in "
                "tests/_matrix_coverage.py, amend ADR 0032, add waivers if needed, then "
                "regenerate the doc (python tests/test_matrix_coverage.py --update)"
            )
            continue
        for component in census_names(census, kind):
            have = cells.get((kind, component), set())
            waived_dims = {dim for (k, c, dim) in WAIVED if k == kind and c == component}
            missing = REQUIRED_DIMS[kind] - have - waived_dims
            if not have and not waived_dims:
                problems.append(f"{kind} {component!r}: no matrix rows at all")
            elif missing:
                problems.append(
                    f"{kind} {component!r}: missing required dim(s) {_dims_label(missing)} (have {_dims_label(have)})"
                )


def _hygiene_problems(
    census: Mapping[str, Mapping[str, object]],
    cells: Mapping[tuple[str, str], set[int]],
    extras: Mapping[str, set[int]],
    problems: list[str],
) -> None:
    """Extra-suite floors, waiver hygiene (both directions), follow-on hygiene."""
    for suite, floor in EXTRA_SUITES.items():
        missing = floor - extras.get(suite, set())
        if missing:
            problems.append(f"extra suite {suite!r}: missing required dim(s) {_dims_label(missing)}")

    for (kind, component, dim), reason in sorted(WAIVED.items()):
        if kind in EXTRA_SUITES:
            continue
        if kind not in census or component not in census_names(census, kind):
            problems.append(f"stale waiver: {kind} {component!r} is not registered ({reason!r})")
        elif dim in cells.get((kind, component), set()):
            problems.append(f"waiver no longer needed: {kind} {component!r} M{dim} now has tests — remove the waiver")

    for row in FOLLOW_ON:
        if row.component is not None and row.kind in census and row.component in census_names(census, row.kind):
            problems.append(
                f"follow-on obligation satisfied: {row.kind} {row.component!r} exists — "
                f"remove the {row.change_id} row and add its matrix rows/policy instead"
            )


def coverage_problems(
    census: Mapping[str, Mapping[str, object]],
    classes: Iterable[MatrixClass],
) -> list[str]:
    """Every policy violation, accumulated — never short-circuited."""
    problems: list[str] = []
    cells, extras = _collect_cells(census, classes, problems)
    _census_floor_problems(census, cells, problems)
    _hygiene_problems(census, cells, extras, problems)
    return problems


def pipeline_kinds(pipelines: Mapping[str, Mapping[str, object]]) -> dict[str, set[str]]:
    """Component kinds exercised by each M8 pipeline, read from typed config fields.

    Never from bare ``"type"`` string literals — the name→kind mapping is not
    injective (``braintrust``/``langfuse`` are registered as both a dataset and a
    sink). Aliases are resolved to canonical names through the census.
    """
    from eval_harness.config import EvalConfig  # local: keeps module import light

    census = registry_census()
    used: dict[str, set[str]] = {kind: set() for kind in census}

    def _canonical(kind: str, name: str) -> str:
        return census_aliases(census, kind).get(name, name)

    for config_dict in pipelines.values():
        config = EvalConfig.model_validate(config_dict)
        used["dataset"].add(_canonical("dataset", config.dataset.type))
        used["target"].add(_canonical("target", config.target.type))
        for scorer in config.scorers:
            used["scorer"].add(_canonical("scorer", scorer.type))
        if config.judge is not None:
            used["judge"].add(_canonical("judge", config.judge.type))
        for sink in config.sinks:
            used["sink"].add(_canonical("sink", sink.type))
    return used


# --------------------------------------------------------------------------- artifact


def doc_path() -> Path:
    return _DOC_PATH


def _count_cells(
    classes: Iterable[MatrixClass],
) -> tuple[dict[tuple[str, str], dict[int, int]], dict[str, dict[int, int]]]:
    """Static method counts per (kind, component) cell and per extra suite."""
    cells: dict[tuple[str, str], dict[int, int]] = {}
    extras: dict[str, dict[int, int]] = {}
    for cls in classes:
        if cls.kind is None:
            continue
        buckets = (
            [extras.setdefault(cls.kind, {})]
            if cls.kind in EXTRA_SUITES
            else [cells.setdefault((cls.kind, component), {}) for component in cls.components]
        )
        for bucket in buckets:
            for dim, count in cls.dim_counts.items():
                bucket[dim] = bucket.get(dim, 0) + count
    return cells, extras


_GRID_DIMS = (1, 2, 3, 5, 6)


def _render_kind_section(
    census: Mapping[str, Mapping[str, object]],
    kind: str,
    cells: Mapping[tuple[str, str], dict[int, int]],
) -> list[str]:
    floor = REQUIRED_DIMS.get(kind, frozenset())
    lines = [
        f"## {kind} (floor: {', '.join(f'M{d}' for d in sorted(floor)) or 'none'})",
        "",
        "| component | " + " | ".join(f"M{d}" for d in _GRID_DIMS) + " |",
        "|---|" + "---|" * len(_GRID_DIMS),
    ]
    waiver_notes: list[str] = []
    for component in census_names(census, kind):
        row = [f"`{component}`"]
        counts = cells.get((kind, component), {})
        for dim in _GRID_DIMS:
            if dim in counts:
                row.append(str(counts[dim]))
            elif (kind, component, dim) in WAIVED:
                row.append("waived")
                waiver_notes.append(f"- `{component}` M{dim} waived: {WAIVED[(kind, component, dim)]}")
            elif dim in floor:
                row.append("MISSING")
            else:
                row.append("—")
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    if waiver_notes:
        lines.extend(waiver_notes)
        lines.append("")
    aliases = census_aliases(census, kind)
    if aliases:
        lines.extend([f"Aliases ({kind}):", "", "| alias | canonical |", "|---|---|"])
        lines.extend(f"| `{alias}` | `{canonical}` |" for alias, canonical in sorted(aliases.items()))
        lines.append("")
    return lines


def _render_tail_sections(
    extras: Mapping[str, dict[int, int]],
    m8: Mapping[str, set[str]],
) -> list[str]:
    lines = [
        "## Extra suites (non-registry rows)",
        "",
        "| suite | floor | dims covered (method counts) |",
        "|---|---|---|",
    ]
    for suite in sorted(EXTRA_SUITES):
        floor_text = ", ".join(f"M{d}" for d in sorted(EXTRA_SUITES[suite]))
        counts = extras.get(suite, {})
        covered = ", ".join(f"M{d}\u00d7{counts[d]}" for d in sorted(counts)) or "none"
        lines.append(f"| {suite} | {floor_text} | {covered} |")
    lines.extend(
        [
            "",
            "## M8 pipelines — kinds exercised",
            "",
            "| kind | canonical components exercised in ≥1 pipeline |",
            "|---|---|",
        ]
    )
    for kind in sorted(m8):
        names = ", ".join(f"`{name}`" for name in sorted(m8[kind])) or "MISSING"
        lines.append(f"| {kind} | {names} |")
    lines.extend(
        [
            "",
            "## Follow-on obligations (queued OpenSpec changes)",
            "",
            "Self-guarded: a row whose component appears in the census fails the guard as",
            '"satisfied — remove the row".',
            "",
            "| change | note |",
            "|---|---|",
        ]
    )
    lines.extend(f"| `{row.change_id}` | {row.note} |" for row in FOLLOW_ON)
    lines.append("")
    return lines


def render_doc() -> str:
    """The committed coverage artifact, deterministically rendered.

    Everything is sorted; counts are static method counts from the AST cell map;
    nothing env-dependent is rendered (registration is unconditional, so the census
    is identical across extras configurations — never render importorskip outcomes).
    """
    census = registry_census()
    classes = extract_matrix_classes(matrix_files())
    from tests.test_matrix_eval_tools import PIPELINES  # local: import cost only when rendering

    m8 = pipeline_kinds(PIPELINES)
    cells, extras = _count_cells(classes)

    lines: list[str] = [
        "<!-- GENERATED FILE - do not edit by hand.",
        "     Regenerate: python tests/test_matrix_coverage.py --update",
        "     Freshness-gated by tests/test_matrix_coverage.py::test_matrix_doc_is_fresh. -->",
        "",
        "# Evaluation test matrix — coverage",
        "",
        "Component \u00d7 dimension coverage of `tests/test_matrix_eval_tools.py`, derived from",
        "the live registries (fresh-subprocess census) and the AST cell map. Cells are",
        "static `test_m<dim>_*` method counts; `waived` cells carry their reason below each",
        "table. Policy (dim floors, waiver rules): ADR 0032; enforcement:",
        "`tests/test_matrix_coverage.py`.",
        "",
        "Dimensions: " + " · ".join(f"M{d} {title}" for d, title in sorted(_DIM_TITLES.items())) + ".",
        "M4 and M7 are global-dynamic (parametrized over the live registries and the",
        "committed baseline); M8 is per-kind (see the pipelines section).",
        "",
    ]
    for kind in sorted(census):
        lines.extend(_render_kind_section(census, kind, cells))
    lines.extend(_render_tail_sections(extras, m8))
    return "\n".join(lines)


def doc_is_fresh() -> tuple[bool, str]:
    """(fresh?, rendered). Missing committed file counts as stale."""
    rendered = render_doc()
    if not _DOC_PATH.exists():
        return (False, rendered)
    return (_DOC_PATH.read_text(encoding="utf-8") == rendered, rendered)
