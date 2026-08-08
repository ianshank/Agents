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
import difflib
import json
import logging
import re
import subprocess
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

#: Module logger, following the repo convention (``getLogger(__name__)`` + lazy %s
#: formatting). Records are emitted at DEBUG/INFO and are therefore invisible by
#: default; pytest surfaces them with ``--log-cli-level=DEBUG`` (or in the captured
#: log of a failing test), which is when a census/extraction question is actually
#: being asked. Nothing here logs at WARNING or above: a real problem is returned as
#: a policy violation or raised, never merely logged.
logger = logging.getLogger(__name__)

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

#: Distributions whose absence would make a matrix class SKIP rather than run. A class
#: that gates itself with ``pytest.importorskip("X")`` claims cells in the artifact that
#: only execute where X is installed, so every gate must appear here AND every value must
#: be installed by the CI job that runs the matrix suite — otherwise the artifact reports
#: coverage CI never verified.
#:
#: This exists because it happened: `TestParquetDataset` gated on `pandas`, which no
#: extra installs, so all four parquet cells skipped in CI while the artifact claimed
#: them. It was caught by review, not by this guard; now the coupling is checked.
SKIP_GATED_IMPORTS: dict[str, str] = {
    "TestAutoevalsScorer": "autoevals",
    "TestOpenAIJudge": "openai",
    "TestAnthropicJudge": "anthropic",
    "TestParquetDataset": "pyarrow",
}

#: The workflow whose install line must satisfy every gate above, and the extras→imports
#: it provides. Kept narrow deliberately: this maps only the gates matrix classes use, so
#: an unrecognised gate fails loudly rather than being assumed satisfied.
MATRIX_CI_WORKFLOW = Path(".github/workflows/eval-harness-ci.yml")
_EXTRA_PROVIDES: dict[str, frozenset[str]] = {
    "dev": frozenset({"pytest", "mypy", "ruff", "jsonschema", "anthropic", "pyarrow"}),
    "langfuse": frozenset({"langfuse"}),
    "openai": frozenset({"openai", "tenacity"}),
    "anthropic": frozenset({"anthropic"}),
    "bedrock": frozenset({"boto3"}),
    "parquet": frozenset({"pyarrow"}),
    "autoevals": frozenset({"autoevals"}),
}

#: The dimension vocabulary. Single source of truth: the method-name pattern and the
#: rendered grid are both derived from it, so adding a ninth dimension here cannot leave
#: a matching method silently uncounted (a hardcoded ``[1-8]`` bound would).
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

_DIM_METHOD_RE = re.compile(rf"^test_m([{min(_DIM_TITLES)}-{max(_DIM_TITLES)}])_")

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
    """One fresh-interpreter census run. Split out so tests can monkeypatch it.

    ``OSError`` is translated rather than allowed to escape: this is called from module
    scope in the guard suite, so a raw ``FileNotFoundError`` / exec-format error on
    ``sys.executable`` would surface as a pytest *collection* error rather than a test
    failure, losing the context. The named conditions mirror
    ``agent_core.subprocess_util``'s three degradation cases, but this raises where that
    degrades: a completeness guard that reports "no signal observed" passes vacuously,
    which is the failure mode ADR 0029 records.
    """
    logger.debug(
        "census probe: %s (cwd %s, timeout %ss)",
        sys.executable,
        _REPO_ROOT,
        _PROBE_TIMEOUT_SECONDS,
    )
    try:
        return subprocess.run(
            [sys.executable, "-c", _PROBE],
            capture_output=True,
            text=True,
            cwd=_REPO_ROOT,
            timeout=_PROBE_TIMEOUT_SECONDS,
        )
    except OSError as exc:  # missing/unexecutable interpreter, permission denied
        raise RuntimeError(f"matrix census probe could not start ({sys.executable!r}): {exc}") from exc


def _as_stream_text(stream: str | bytes | None) -> str:
    """A captured stream rendered for a human, whatever shape it arrives in."""
    if stream is None:
        return ""
    if isinstance(stream, bytes):
        return stream.decode("utf-8", errors="replace")
    return stream


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
        # Carry the partial streams: a probe that hangs mid-import (a blocking import, a
        # lock) leaves its most useful evidence there, and only the message reaches a CI
        # log. `text=True` should make these str, but TimeoutExpired's contract allows
        # bytes, so decode defensively rather than rendering a b'...' repr.
        raise RuntimeError(
            f"matrix census probe did not finish within {_PROBE_TIMEOUT_SECONDS}s\n"
            f"partial stdout:\n{_as_stream_text(exc.stdout)}\n"
            f"partial stderr:\n{_as_stream_text(exc.stderr)}"
        ) from exc
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
    census = _parse_census(data, source="census probe")
    # Once-per-run summary (lru_cache guarantees a single emission per process), per the
    # AGENTS.md logging convention: info for run summaries, debug for per-call detail.
    logger.info(
        "census: %d kind(s), %d component(s) — %s",
        len(census),
        sum(len(census_names(census, kind)) for kind in census),
        {kind: len(census_names(census, kind)) for kind in sorted(census)},
    )
    return census


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
    #: True when a ``MATRIX_COMPONENTS`` assignment was seen at all, even if its value
    #: did not parse as a literal string tuple. Lets the policy check distinguish "you
    #: forgot to declare components" from "you declared them in a shape the extractor
    #: cannot read" (a bare string is the likely typo: it is iterable, so a naive
    #: extractor would silently yield per-character components).
    components_declared: bool = False
    #: Base-class names other than ``object``. Inherited ``test_m*`` methods live in the
    #: base's AST, not this class's, so a matrix class with bases would under-count its
    #: own cells; the policy check refuses rather than under-counting silently.
    bases: tuple[str, ...] = ()

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


def _base_names(node: ast.ClassDef) -> tuple[str, ...]:
    """Base-class names other than ``object``, best-effort (``Name`` / dotted ``Attribute``)."""
    names: list[str] = []
    for base in node.bases:
        if isinstance(base, ast.Name):
            rendered = base.id
        elif isinstance(base, ast.Attribute):
            rendered = base.attr
        else:  # a subscripted/generic base: record its shape rather than dropping it
            rendered = type(base).__name__
        if rendered != "object":
            names.append(rendered)
    return tuple(names)


def _class_declarations(
    node: ast.ClassDef, module_tuples: Mapping[str, tuple[str, ...]]
) -> tuple[str | None, tuple[str, ...], bool, bool, dict[int, int]]:
    """(kind, components, components_declared, registry_marker, dim_counts) for one class."""
    kind: str | None = None
    components: tuple[str, ...] = ()
    components_declared = False
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
                components_declared = True
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
    return kind, components, components_declared, registry_marker, dim_counts


def extract_matrix_classes(paths: Iterable[Path]) -> list[MatrixClass]:
    """Every ``Test*`` class in ``paths``, with its declarations and dim counts.

    Only top-level classes are read: a matrix class nested inside another class or a
    function would not be collected as a matrix row by convention, and reading one would
    invite declarations that pytest never runs.
    """
    classes: list[MatrixClass] = []
    path_list = list(paths)  # materialised: `paths` may be a generator, and it is logged below
    for path in path_list:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        module_tuples = _module_literal_tuples(tree)
        for node in tree.body:
            if not isinstance(node, ast.ClassDef) or not node.name.startswith("Test"):
                continue
            kind, components, declared, registry_marker, dim_counts = _class_declarations(node, module_tuples)
            classes.append(
                MatrixClass(
                    module=path.name,
                    name=node.name,
                    kind=kind,
                    components=components,
                    registry_marker=registry_marker,
                    dim_counts=dim_counts,
                    components_declared=declared,
                    bases=_base_names(node),
                )
            )
    logger.debug(
        "cell map: %d class(es) across %d file(s), %d declared cell(s)",
        len(classes),
        len(path_list),
        sum(len(c.dim_counts) for c in classes),
    )
    return classes


def importorskip_gates(paths: Iterable[Path]) -> dict[str, str]:
    """``{class name: imported distribution}`` for every ``importorskip`` in a matrix class.

    A gated class runs only where its distribution is installed, so its cells are claimed
    in the artifact but conditionally verified. Extracted so the coupling to the CI install
    line can be asserted instead of assumed.
    """
    gates: dict[str, str] = {}
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            for call in ast.walk(node):
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "importorskip"
                    and call.args
                    and isinstance(call.args[0], ast.Constant)
                    and isinstance(call.args[0].value, str)
                ):
                    gates[node.name] = call.args[0].value
    return gates


def ci_installed_imports(workflow_text: str) -> frozenset[str]:
    """Distributions the matrix CI job installs, resolved from its extras.

    Reads the ``install:`` line's ``.[a,b,c]`` extras and maps them through
    ``_EXTRA_PROVIDES``. An extra with no mapping contributes nothing — unknown extras
    must not be silently credited with providing an import.
    """
    provided: set[str] = set()
    for extras in re.findall(r"install:[^\n]*\.\[([^\]]+)\]", workflow_text):
        for extra in extras.split(","):
            provided |= _EXTRA_PROVIDES.get(extra.strip(), frozenset())
    return frozenset(provided)


def skip_gate_problems(paths: Iterable[Path], workflow_text: str) -> list[str]:
    """Every matrix cell claimed in the artifact must actually execute in CI.

    Two directions, because both have bitten: an undeclared gate (a class that skips
    without saying so) and an unsatisfied gate (a declared distribution the CI job does
    not install — the parquet defect).
    """
    problems: list[str] = []
    found = importorskip_gates(paths)
    installed = ci_installed_imports(workflow_text)
    for class_name, distribution in sorted(found.items()):
        if class_name not in SKIP_GATED_IMPORTS:
            problems.append(
                f"{class_name} gates on importorskip({distribution!r}) but is absent from "
                "SKIP_GATED_IMPORTS — a gated class claims cells that only conditionally run"
            )
        elif SKIP_GATED_IMPORTS[class_name] != distribution:
            problems.append(
                f"{class_name}: SKIP_GATED_IMPORTS says {SKIP_GATED_IMPORTS[class_name]!r} "
                f"but the class gates on {distribution!r}"
            )
    for class_name, distribution in sorted(SKIP_GATED_IMPORTS.items()):
        if class_name not in found:
            problems.append(
                f"stale skip gate: {class_name} no longer calls importorskip — remove it from "
                "SKIP_GATED_IMPORTS (its cells now run unconditionally)"
            )
        elif distribution not in installed:
            problems.append(
                f"{class_name} skips unless {distribution!r} is installed, but "
                f"{MATRIX_CI_WORKFLOW}'s install line provides only {sorted(installed)} — "
                "its matrix cells would be claimed in the artifact and never verified in CI"
            )
    return problems


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
        # Nested classes are visited too, and each violation is attributed to its
        # INNERMOST enclosing class, so nesting is neither an evasion nor a misreport.
        for node in _iter_classdefs(tree):
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
            inner_classes = [c for c in _iter_classdefs(node) if c is not node]
            for call in ast.walk(node):
                if not (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "parametrize"
                ):
                    continue
                argvalues = _parametrize_argvalues(call)
                if argvalues is None or not _is_all_literal(argvalues):
                    continue
                # Skip calls that belong to a nested class: that class is visited on its
                # own iteration and judged on its own designation.
                if any(inner.lineno <= call.lineno <= (inner.end_lineno or inner.lineno) for inner in inner_classes):
                    continue
                violations.append(
                    f"{path.name}::{node.name}: parametrize over a constant literal "
                    f"(line {argvalues.lineno}) — derive from the census/baseline instead"
                )
    return violations


def _is_all_literal(node: ast.expr) -> bool:
    """Whether an expression is built entirely from constant literals, at any nesting.

    Covers dicts, negative numbers and f-strings-of-constants as well as the obvious
    sequence forms: a list-of-dicts restatement of the registry surface is the same
    banned defect in a different shape, and would otherwise pass.
    """
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return all(_is_all_literal(el) for el in node.elts)
    if isinstance(node, ast.Dict):
        return all(k is not None and _is_all_literal(k) for k in node.keys) and all(
            _is_all_literal(v) for v in node.values
        )
    if isinstance(node, ast.UnaryOp):  # -1, +1, not True
        return _is_all_literal(node.operand)
    if isinstance(node, ast.JoinedStr):  # f"{'a'}" over constants only
        return all(_is_all_literal(v.value) if isinstance(v, ast.FormattedValue) else True for v in node.values)
    return False


def _iter_classdefs(node: ast.AST) -> Iterable[ast.ClassDef]:
    """Every ``ClassDef`` at any nesting, innermost-attributable.

    The ban must not be evadable by nesting a designated class inside another class or
    an ``if`` block, which a ``tree.body``-only scan would miss.
    """
    for child in ast.walk(node):
        if isinstance(child, ast.ClassDef):
            yield child


def _parametrize_argvalues(call: ast.Call) -> ast.expr | None:
    """The argvalues expression of a ``parametrize`` call, positional or by keyword."""
    if len(call.args) >= 2:
        return call.args[1]
    for keyword in call.keywords:
        if keyword.arg == "argvalues":
            return keyword.value
    return None


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
            if cls.components:
                # Components on a non-registry suite are silently unused, and the likely
                # cause is a mistyped MATRIX_KIND — which would also strand every cell
                # the class declares, reported elsewhere as "no matrix rows at all".
                problems.append(
                    f"{cls.module}::{cls.name}: extra suite {cls.kind!r} takes no MATRIX_COMPONENTS "
                    f"(got {list(cls.components)}) — drop them, or fix a mistyped MATRIX_KIND"
                )
            extras.setdefault(cls.kind, set()).update(cls.dims)
            continue
        if cls.kind not in REQUIRED_DIMS:
            problems.append(
                f"{cls.module}::{cls.name}: unknown MATRIX_KIND {cls.kind!r} — "
                "add a REQUIRED_DIMS row in tests/_matrix_coverage.py (and amend ADR 0032)"
            )
            continue
        if cls.bases:
            # Inherited test_m* methods live in the base's AST, so counting only this
            # class's body would under-count cells pytest actually runs. Refuse instead
            # of silently under-counting (which would demand rows that already exist).
            problems.append(
                f"{cls.module}::{cls.name}: matrix classes must not inherit "
                f"(bases: {list(cls.bases)}) — inherited test_m*_ methods are invisible to the "
                "AST cell map; inline the methods or parametrize a single class instead"
            )
            continue
        if not cls.components:
            detail = (
                "MATRIX_COMPONENTS is declared but is not a literal string tuple "
                '(a bare string such as MATRIX_COMPONENTS = "exact_match" is not a tuple; '
                'write ("exact_match",) — note the trailing comma)'
                if cls.components_declared
                else "MATRIX_KIND set but MATRIX_COMPONENTS is missing"
            )
            problems.append(f"{cls.module}::{cls.name}: {detail}")
            continue
        if not cls.dim_counts:
            # A declaration with no dim methods of its own contributes nothing. The usual
            # cause is inheritance (already refused above) or a renamed method that no
            # longer matches the test_m<dim>_ convention.
            problems.append(
                f"{cls.module}::{cls.name}: declares {cls.kind}/{list(cls.components)} but has no "
                "test_m<dim>_ methods of its own"
            )
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

    # Waiver keys are validated first: WAIVED is the one policy table with no schema of
    # its own, so a waiver naming a non-registry kind or a dim outside that kind's floor
    # would sit in the file looking authoritative while having no effect anywhere.
    for (kind, component, dim), reason in sorted(WAIVED.items()):
        if kind not in REQUIRED_DIMS:
            problems.append(
                f"inert waiver: {kind!r} is not a registry kind with a REQUIRED_DIMS floor "
                f"({reason!r}) — extra suites are waived by editing their floor, not WAIVED"
            )
            continue
        if dim not in REQUIRED_DIMS[kind]:
            problems.append(
                f"inert waiver: {kind} {component!r} M{dim} — M{dim} is not in {kind}'s floor "
                f"{_dims_label(REQUIRED_DIMS[kind])}, so waiving it changes nothing"
            )
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
    if not census:
        # A census that measured nothing must never satisfy the floors vacuously — the
        # ADR 0029 lesson this repo is built on (a metric reporting a pass having
        # measured nothing). Guarded here, not only in the suite's populated-census
        # test, so every caller (F_053, the renderer) inherits the refusal.
        problems.append(
            "census is empty: no registries were discovered, so no floor could be checked — "
            "this is a probe failure, not a complete matrix"
        )
        return problems
    cells, extras = _collect_cells(census, classes, problems)
    _census_floor_problems(census, cells, problems)
    _hygiene_problems(census, cells, extras, problems)
    logger.debug(
        "policy: %d kind(s), %d cell(s) declared, %d problem(s)",
        len(census),
        len(cells),
        len(problems),
    )
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


def _cell(text: str) -> str:
    """Prose rendered safely into a markdown table cell.

    A ``|`` fabricates a column and a newline splits the row — and because the freshness
    gate compares rendered-vs-committed, both sides would be corrupted identically and
    the gate would stay green while the published artifact was wrong.
    """
    return " ".join(text.split()).replace("|", "\\|")


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


#: Columns of the rendered per-kind grid, DERIVED from the policy rather than listed.
#: A hardcoded tuple silently under-reported the artifact: `_render_kind_section` only
#: reaches its `MISSING` branch for dims it iterates, so adding M4 or M7 to any kind's
#: floor would have the guard enforce the cell correctly while the committed doc omitted
#: the column entirely — a genuinely missing cell rendering as no cell at all.
#: `EXTRA_SUITES` dims are excluded on purpose: M8 is a non-registry, per-kind property
#: reported in its own section, not a per-component grid column.
_GRID_DIMS: tuple[int, ...] = tuple(sorted(set().union(*REQUIRED_DIMS.values())))


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
                waiver_notes.append(f"- `{component}` M{dim} waived: {_cell(WAIVED[(kind, component, dim)])}")
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
    lines.extend(f"| `{_cell(row.change_id)}` | {_cell(row.note)} |" for row in FOLLOW_ON)
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


#: How many diff lines a staleness report shows before truncating. A bounded diff keeps
#: a CI log readable while still naming the drift; the full artifact is one command away.
MAX_DIFF_LINES = 40

REGEN_HINT = "regenerate and commit: python tests/test_matrix_coverage.py --update"


def freshness_failure_message(rendered: str) -> str:
    """Why the committed artifact is stale, not merely that it is.

    Emitting the actual diff — rather than logging a count or printing only the hint —
    puts the drift where a CI reader looks: in the failure output. Applies the
    ``mermaid_gen --check`` dual-channel idea at the level that helps.
    """
    if not _DOC_PATH.exists():
        return f"{_DOC_PATH} does not exist — {REGEN_HINT}"
    committed = _DOC_PATH.read_text(encoding="utf-8").splitlines()
    diff = list(
        difflib.unified_diff(
            committed,
            rendered.splitlines(),
            fromfile=f"{_DOC_PATH.name} (committed)",
            tofile=f"{_DOC_PATH.name} (regenerated)",
            lineterm="",
            n=1,
        )
    )
    shown = diff[:MAX_DIFF_LINES]
    if len(diff) > MAX_DIFF_LINES:
        shown.append(f"... {len(diff) - MAX_DIFF_LINES} more diff line(s) truncated")
    return f"{_DOC_PATH} is stale — {REGEN_HINT}\n" + "\n".join(shown)
