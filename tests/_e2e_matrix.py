"""Engine for the generated end-to-end test matrix.

Three moving parts, mirroring :mod:`tests._matrix_coverage` (ADR 0032):

* **census** - what the run actually did, read from ``artifacts/e2e-report/`` (the
  ``summary.json`` records plus the per-suite JUnit XML).
* **declared inventory** - what the runner *can* do, parsed out of
  ``scripts/run_all_e2e.ps1``. Nothing about the step list is restated here; a step
  added to the runner appears in the matrix without touching this module, and a step
  observed in a run that the runner does not declare is a hard error.
* **policy** - the cross-checks that stop a vacuous artifact: an empty census never
  renders, and a run whose observed steps are not a subset of the declared ones fails
  rather than quietly dropping rows.

Everything else (package list, coverage floors, live-step credentials, CI workflows) is
derived from the file that owns it, never copied into this module. The per-fact sources
are documented on each ``derive_*`` function.

The rendered artifact is deterministic: sorted throughout, POSIX paths, LF endings, and
no wall-clock anywhere except the explicitly-passed provenance stamp.
"""

from __future__ import annotations

import configparser
import csv
import difflib
import io
import json
import logging
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent

#: Where ``run_all_e2e.ps1`` writes its report (``$Report``). Gitignored; recreated per run.
DEFAULT_REPORT_DIR = _REPO_ROOT / "artifacts" / "e2e-report"

#: Where the committed artifact lives.
DEFAULT_OUT_DIR = _REPO_ROOT / "docs" / "e2e-matrix"

#: The runner whose step inventory this matrix mirrors.
RUNNER_PATH = _REPO_ROOT / "scripts" / "run_all_e2e.ps1"

#: PowerShell writes ``summary.json`` with ``Set-Content -Encoding UTF8``, which emits a
#: BOM on Windows PowerShell 5.1. ``json.load`` rejects a BOM under plain utf-8, so every
#: read of a runner-produced file goes through this codec instead.
RUNNER_TEXT_ENCODING = "utf-8-sig"

#: Status recorded for a declared step that the run never reached (tier not selected, or a
#: conditional branch not taken). Deliberately distinct from SKIP, which the runner emits
#: for a step it *did* reach and consciously declined to execute.
NOT_RUN = "NOT-RUN"

#: Marker used where the runner's own default applies (``$WorkDir = $RepoRoot``).
REPO_ROOT_MARKER = "."

#: Bounded diff emitted when the committed artifact is stale.
MAX_DIFF_LINES = 40

REGEN_HINT = "regenerate and commit: python tests/test_e2e_matrix.py --update"

GENERATED_BANNER = (
    "GENERATED FILE - do not edit by hand.\n"
    "Regenerate: python tests/test_e2e_matrix.py --update\n"
    "Freshness-gated by tests/test_e2e_matrix.py::test_matrix_artifact_is_fresh."
)


class MatrixError(RuntimeError):
    """A derivation or policy failure that must stop the render."""


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RunStep:
    """One row of ``summary.json`` - exactly the five fields ``Add-Result`` records."""

    tier: str
    name: str
    status: str
    detail: str
    duration_ms: int


@dataclass(frozen=True)
class DeclaredStep:
    """One step the runner can emit, parsed from ``run_all_e2e.ps1``."""

    tier: str
    name: str
    command: str = ""
    workdir: str = REPO_ROOT_MARKER

    @property
    def area(self) -> str:
        """The step-name prefix (``suite``, ``cli``, ``live``, ...); the whole name if bare."""
        return self.name.split(":", 1)[0] if ":" in self.name else self.name


@dataclass(frozen=True)
class SuiteArtifact:
    """Aggregated counters from one JUnit file."""

    tests: int = 0
    failures: int = 0
    errors: int = 0
    skipped: int = 0


@dataclass(frozen=True)
class PackageFacts:
    """A gated unit and the coverage floor it declares, with every anchor that states it."""

    name: str
    floor: int | None
    anchors: tuple[str, ...] = ()
    workflows: tuple[str, ...] = ()


@dataclass(frozen=True)
class Provenance:
    """Run identity. Every volatile value is injected so the render stays a pure function."""

    sha: str
    branch: str
    generated_at: str
    host: str
    python_version: str
    runner_invocation: str


@dataclass(frozen=True)
class Sheet:
    """One tab of the workbook, and one CSV file. Rows are pre-stringified."""

    name: str
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...] = ()
    notes: tuple[str, ...] = field(default=())


# ---------------------------------------------------------------------------
# Census: what the run did
# ---------------------------------------------------------------------------


def load_run_steps(report_dir: Path) -> tuple[RunStep, ...]:
    """Read ``summary.json`` into records.

    Tolerates the two shapes PowerShell's ``ConvertTo-Json`` produces: an array for two or
    more results, and a bare object for exactly one. A single-result run is degenerate but
    real (a failed pre-flight aborts immediately), and silently returning no rows for it
    would be the vacuous pass this artifact exists to prevent.
    """
    path = report_dir / "summary.json"
    if not path.is_file():
        raise MatrixError(f"no run report at {path.as_posix()} - run scripts/run_all_e2e.ps1 first")
    try:
        payload = json.loads(path.read_text(encoding=RUNNER_TEXT_ENCODING))
    except (OSError, json.JSONDecodeError) as exc:
        raise MatrixError(f"cannot read {path.as_posix()}: {exc}") from exc

    records = [payload] if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise MatrixError(f"{path.as_posix()} is neither an object nor an array")

    steps: list[RunStep] = []
    for entry in records:
        if not isinstance(entry, Mapping):
            raise MatrixError(f"{path.as_posix()} contains a non-object result: {entry!r}")
        steps.append(
            RunStep(
                tier=str(entry.get("tier", "")),
                name=str(entry.get("name", "")),
                status=str(entry.get("status", "")),
                detail=str(entry.get("detail", "")),
                duration_ms=_as_int(entry.get("duration_ms")),
            )
        )
    logger.info("census: %d step result(s) from %s", len(steps), path.as_posix())
    return tuple(steps)


def _as_int(value: object) -> int:
    """Best-effort int; a malformed duration must not sink the whole report."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def load_junit(report_dir: Path) -> dict[str, SuiteArtifact]:
    """Aggregate every ``*.xml`` in the report directory by file stem.

    Richer than the runner's own reading, which sums ``tests`` only (``Get-JUnitTestCount``)
    and then renders it as prose into ``detail``.
    """
    artifacts: dict[str, SuiteArtifact] = {}
    if not report_dir.is_dir():
        return artifacts
    for path in sorted(report_dir.glob("*.xml")):
        try:
            root = ET.parse(path).getroot()
        except (OSError, ET.ParseError) as exc:
            logger.warning("unreadable JUnit file %s (%s); counts omitted", path.name, exc)
            continue
        suites = list(root.iter("testsuite"))
        artifacts[path.stem] = SuiteArtifact(
            tests=sum(_as_int(s.get("tests")) for s in suites),
            failures=sum(_as_int(s.get("failures")) for s in suites),
            errors=sum(_as_int(s.get("errors")) for s in suites),
            skipped=sum(_as_int(s.get("skipped")) for s in suites),
        )
    logger.debug("junit: %d suite file(s) parsed", len(artifacts))
    return artifacts


def safe_step_name(name: str) -> str:
    """The runner's ``$SafeName`` scriptblock: ``($n -replace '[^\\w.-]', '_')``.

    Reimplemented rather than guessed because it determines the per-step log filename, and
    the Evidence column is only useful if it points at a file that exists.
    """
    return re.sub(r"[^\w.-]", "_", name)


def evidence_for(step_name: str, report_dir: Path) -> str:
    """Repo-relative log path for a step, or ``""`` when the runner wrote none."""
    log = report_dir / f"{safe_step_name(step_name)}.log"
    if not log.is_file():
        return ""
    try:
        return log.relative_to(_REPO_ROOT).as_posix()
    except ValueError:
        return log.as_posix()


# ---------------------------------------------------------------------------
# Declared inventory: what the runner can do
# ---------------------------------------------------------------------------

# Steps recorded with a literal tier and a literal name. Not line-anchored: several sites
# sit inside `catch { ... }` / `else { ... }` on the same physical line.
_LITERAL_STEP_RE = re.compile(
    r"(?:Invoke-PytestStep|Invoke-CmdStep|Add-Result)\s+'(?P<tier>[A-Z]+)'\s+'(?P<name>[^']+)'"
)

# Steps whose name comes from a hashtable element of an array the runner loops over,
# e.g. `Invoke-PytestStep 'A' $s.name` with `foreach ($s in $suites)`.
_VARIABLE_STEP_RE = re.compile(
    r"(?:Invoke-PytestStep|Invoke-CmdStep|Add-Result)\s+'(?P<tier>[A-Z]+)'\s+\$(?P<item>\w+)\.name"
    r"(?:\s+\$(?P<args_var>\w+))?"
)

_FOREACH_RE = re.compile(r"foreach\s*\(\s*\$(?P<item>\w+)\s+in\s+\$(?P<collection>\w+)\s*\)")

# Leading whitespace is significant here: `$suites` sits at column 0 but `$liveJudges` is
# nested inside the tier-D `if` block. Anchoring at `^\$` silently matched only the first,
# so every judge step vanished from the inventory while the parse still "succeeded".
_ARRAY_BLOCK_RE = re.compile(r"^[ \t]*\$(?P<var>\w+)\s*=\s*@\(\s*$(?P<body>.*?)^[ \t]*\)\s*$", re.MULTILINE | re.DOTALL)

_HASH_ENTRY_RE = re.compile(r"@\{[^}]*?\bname\s*=\s*'(?P<name>[^']+)'[^}]*?\}", re.DOTALL)

_HASH_DIR_RE = re.compile(r"\bdir\s*=\s*(?P<dir>[^;}]+)")

# The python argument array that follows a step name on the (continuation-joined) call line.
_ARGS_RE = re.compile(r"@\((?P<args>[^)]*)\)")

_QUOTED_RE = re.compile(r"'([^']*)'")

# `Join-Path $RepoRoot 'agent-core'` and friends: keep the human-meaningful tail.
_JOIN_PATH_RE = re.compile(r"Join-Path\s+\$\w+\s+'(?P<tail>[^']+)'")


def _join_continuations(text: str) -> str:
    """Fold PowerShell backtick line-continuations so one logical call is one line."""
    return re.sub(r"`[ \t]*\r?\n[ \t]*", " ", text.replace("\r\n", "\n"))


def _balanced_args(text: str, start: int) -> str | None:
    """Inner text of the first ``@( ... )`` at or after *start*, spanning newlines.

    A regex cannot do this. PowerShell keeps an expression open inside parentheses, so an
    argument array is routinely written across several lines with no backtick continuation
    -- and a ``@\\([^)]*\\)`` pattern stops at the first inner ``)`` anyway. Reading 57% of
    the runner's steps as "no command" is what that costs, so the parens are matched.
    """
    open_at = text.find("@(", start)
    if open_at == -1:
        return None
    depth = 0
    for index in range(open_at + 1, len(text)):
        char = text[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[open_at + 2 : index]
    return None


def _resolve_array_literal(text: str, variable: str) -> str | None:
    """Inner text of ``$<variable> = @( ... )``, wherever it is indented."""
    match = re.search(rf"\${re.escape(variable)}\s*=\s*(?=@\()", text)
    return _balanced_args(text, match.end()) if match else None


def _render_command(args_text: str | None) -> str:
    """Render a PowerShell argument array as a readable ``python ...`` command line."""
    if args_text is None:
        return ""
    tokens = _QUOTED_RE.findall(args_text)
    if not tokens:
        # An all-variable array (e.g. @($SkipExitCode)) carries no readable literal.
        return ""
    return "python " + " ".join(tokens)


def _command_from(text: str, after: int) -> str:
    """Command for a step call, taken only from the array that *immediately* follows it.

    The adjacency requirement is the whole point. Scanning ahead for the next ``@(`` instead
    made ``Add-Result 'PRE' 'preflight-imports' 'PASS' '...'`` -- a call with no argument
    array at all -- adopt the ``$suites`` literal declared further down the file, and report
    it as that step's command. A step either has its arguments right there or has none.
    """
    if re.match(r"\s*(?=@\()", text[after:]) is None:
        return ""
    return _render_command(_balanced_args(text, after))


def _array_blocks(text: str) -> dict[str, str]:
    """Map ``$name`` -> the body of a top-level ``@( ... )`` array literal."""
    return {m.group("var"): m.group("body") for m in _ARRAY_BLOCK_RE.finditer(text)}


def _loop_bindings(text: str) -> dict[str, str]:
    """Map a ``foreach`` item variable to the collection it iterates."""
    return {m.group("item"): m.group("collection") for m in _FOREACH_RE.finditer(text)}


def parse_declared_steps(runner_text: str) -> tuple[DeclaredStep, ...]:
    """Every step ``run_all_e2e.ps1`` can record, derived from its call sites.

    Two declaration styles are handled because the runner uses both: literal
    ``Invoke-*Step 'TIER' 'name'`` calls, and loops over an array of hashtables
    (``$suites``, ``$liveJudges``) whose ``name`` supplies the step. A step is emitted once
    even though several branches record it (a PASS path and a SKIP path, say).
    """
    text = _join_continuations(runner_text)
    blocks = _array_blocks(text)
    bindings = _loop_bindings(text)

    declared: dict[str, DeclaredStep] = {}

    def record(step: DeclaredStep) -> None:
        """First declaration wins, but a later one may fill in a command it lacked.

        A step is typically recorded twice: once on the branch that runs it and once on a
        SKIP/failure branch that only calls ``Add-Result``. Whichever comes first in the file
        is arbitrary, so plain first-wins left every judge step with an empty command.
        """
        existing = declared.get(step.name)
        if existing is None:
            declared[step.name] = step
        elif step.command and not existing.command:
            declared[step.name] = DeclaredStep(
                tier=existing.tier, name=existing.name, command=step.command, workdir=existing.workdir
            )

    for match in _LITERAL_STEP_RE.finditer(text):
        name = match.group("name")
        record(DeclaredStep(tier=match.group("tier"), name=name, command=_command_from(text, match.end())))

    for match in _VARIABLE_STEP_RE.finditer(text):
        collection = bindings.get(match.group("item"))
        body = blocks.get(collection or "")
        if body is None:
            logger.warning("cannot resolve $%s.name to an array literal; steps may be missing", match.group("item"))
            continue
        # The loop passes its argument array by variable (`... $s.name $suiteArgs ...`), so
        # every step in the collection shares one command; resolve it once per loop.
        shared = match.group("args_var")
        command = _render_command(_resolve_array_literal(text, shared)) if shared else _command_from(text, match.end())
        for entry in _HASH_ENTRY_RE.finditer(body):
            record(
                DeclaredStep(
                    tier=match.group("tier"),
                    name=entry.group("name"),
                    command=command,
                    workdir=_workdir_from(entry.group(0)),
                )
            )

    # `Invoke-Py -Name 'x' -PyArgs @(...)` is a third form: the pre-flight guard runs through
    # it and records its result separately, so the name is known but the command is not.
    for match in re.finditer(r"Invoke-Py\s+-Name\s+'(?P<name>[^']+)'\s+-PyArgs\s*(?=@\()", text):
        step = declared.get(match.group("name"))
        if step is not None and not step.command:
            declared[step.name] = DeclaredStep(
                tier=step.tier,
                name=step.name,
                command=_render_command(_balanced_args(text, match.end())),
                workdir=step.workdir,
            )

    if not declared:
        raise MatrixError(f"no steps parsed from {RUNNER_PATH.name}; the call-site grammar has changed")
    logger.info("declared: %d step(s) parsed from %s", len(declared), RUNNER_PATH.name)
    return tuple(sorted(declared.values(), key=lambda s: (s.tier, s.name)))


def _workdir_from(hash_text: str) -> str:
    """Working directory of a ``$suites`` entry, or the runner's repo-root default."""
    match = _HASH_DIR_RE.search(hash_text)
    if match is None:
        return REPO_ROOT_MARKER
    joined = _JOIN_PATH_RE.search(match.group("dir"))
    return joined.group("tail") if joined else REPO_ROOT_MARKER


# ---------------------------------------------------------------------------
# Derived facts: packages, floors, credentials, workflows
# ---------------------------------------------------------------------------


def derive_members(root: Path) -> tuple[str, ...]:
    """Workspace members, from the same detector the Makefile generator uses.

    Source: ``skills/project-setup/scripts/makegen/workspace.py``. Imported rather than
    reimplemented so the matrix and the build system can never disagree about what a
    member is.
    """
    import sys

    detector_dir = root / "skills" / "project-setup" / "scripts"
    if str(detector_dir) not in sys.path:
        sys.path.append(str(detector_dir))
    from makegen.workspace import detect_workspace

    facts = detect_workspace(root)
    if facts.skipped:
        logger.warning("workspace detector skipped non-safe member name(s): %s", ", ".join(facts.skipped))
    return tuple(str(member) for member in facts.members)


def makefile_check_members(root: Path) -> tuple[str, ...]:
    """Members named by the Makefile's ``check-all`` prerequisites.

    A second, independent anchor for the member list. The two are asserted equal by the
    test suite, which is how a Makefile regenerated against a changed tree gets noticed.
    """
    makefile = root / "Makefile"
    if not makefile.is_file():
        return ()
    for line in makefile.read_text(encoding="utf-8").splitlines():
        if line.startswith("check-all:"):
            body = line.split(":", 1)[1].split("##", 1)[0]
            return tuple(sorted(tok[len("check-") :] for tok in body.split() if tok.startswith("check-")))
    return ()


def _floor_from_pyproject(path: Path) -> int | None:
    """``[tool.coverage.report] fail_under`` read without a TOML dependency.

    A regex section read, for the same reason ``check_charter_invariants`` uses one: this
    must work on the CI floor of Python 3.10, where ``tomllib`` is absent and ``scripts/``
    deliberately carries no ``tomli`` dependency.
    """
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    section = re.search(r"^\[tool\.coverage\.report\](?P<body>.*?)(?=^\[|\Z)", text, re.MULTILINE | re.DOTALL)
    if section is None:
        return None
    value = re.search(r"^\s*fail_under\s*=\s*\"?(?P<n>\d+)", section.group("body"), re.MULTILINE)
    return int(value.group("n")) if value else None


def _floor_from_gate_script(path: Path) -> int | None:
    """``COV_FAIL_UNDER="${COV_FAIL_UNDER:-N}"`` from a generated quality-gate script."""
    if not path.is_file():
        return None
    match = re.search(r"COV_FAIL_UNDER=\"\$\{COV_FAIL_UNDER:-(?P<n>\d+)\}\"", path.read_text(encoding="utf-8"))
    return int(match.group("n")) if match else None


def _floor_from_coveragerc(path: Path) -> int | None:
    """``[report] fail_under`` from an INI coverage config."""
    if not path.is_file():
        return None
    parser = configparser.ConfigParser()
    try:
        parser.read(path, encoding="utf-8")
        return parser.getint("report", "fail_under")
    except (configparser.Error, ValueError) as exc:
        logger.warning("cannot read a coverage floor from %s (%s)", path.as_posix(), exc)
        return None


def derive_packages(root: Path, workflows: Mapping[str, tuple[str, ...]]) -> tuple[PackageFacts, ...]:
    """Every gated unit with its declared coverage floor and the anchors that declare it.

    Each unit's floor is read from up to three independent places - its ``pyproject.toml``,
    its generated ``quality-gate.sh``, and (for ``scripts``) ``.coveragerc``. Disagreement
    between anchors is a finding, not something this module papers over, so every value
    found is reported and the test suite asserts they agree.
    """
    units: list[PackageFacts] = []
    roots: list[tuple[str, Path]] = [("root", root)]
    roots += [(name, root / name) for name in derive_members(root)]
    roots.append(("experiments/backend-validation", root / "experiments" / "backend-validation"))

    for name, base in roots:
        anchors: list[str] = []
        floors: list[int] = []
        for label, value in (
            ("pyproject.toml", _floor_from_pyproject(base / "pyproject.toml")),
            ("quality-gate.sh", _floor_from_gate_script(base / "scripts" / "quality-gate.sh")),
        ):
            if value is not None:
                anchors.append(f"{label}={value}")
                floors.append(value)
        units.append(
            PackageFacts(
                name=name,
                floor=floors[0] if floors else None,
                anchors=tuple(anchors),
                workflows=workflows.get(name, ()),
            )
        )

    scripts_floor = _floor_from_coveragerc(root / "scripts" / ".coveragerc")
    units.append(
        PackageFacts(
            name="scripts",
            floor=scripts_floor,
            anchors=(f"scripts/.coveragerc={scripts_floor}",) if scripts_floor is not None else (),
            workflows=workflows.get("scripts", ()),
        )
    )
    return tuple(sorted(units, key=lambda u: u.name))


def derive_workflows(root: Path) -> dict[str, tuple[str, ...]]:
    """Map a gated unit to the CI workflows that run it.

    Derived from each workflow's ``working-directory:`` values; a workflow that sets none
    but invokes the shared quality-gate action is running at the repo root, which is what
    the action's own default says.
    """
    mapping: dict[str, set[str]] = {}
    workflow_dir = root / ".github" / "workflows"
    if not workflow_dir.is_dir():
        return {}
    for path in sorted(workflow_dir.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        dirs = {m.group("d").strip().strip("\"'") for m in re.finditer(r"working-directory:\s*(?P<d>\S+)", text)}
        if not dirs and "run-quality-gate" in text:
            dirs = {"root"}
        for directory in dirs:
            key = "root" if directory in {".", "root"} else directory
            mapping.setdefault(key, set()).add(path.name)
    return {key: tuple(sorted(names)) for key, names in mapping.items()}


def derive_live_credentials(root: Path) -> dict[str, tuple[str, ...]]:
    """Required environment variables for every live step.

    Composed from the two places that own the answer: the Python smokes for the
    langfuse/phoenix steps, and ``$liveJudges[].env`` for the judges.
    """
    creds = smoke_credentials(root)
    creds.update(_judge_credentials(root))
    return creds


def smoke_credentials(root: Path) -> dict[str, tuple[str, ...]]:
    """Required variables for the smoke-backed live steps, read from the smokes themselves.

    The two smokes spell the requirement differently - ``REQUIRED_ENV`` is a tuple in one,
    ``ENV_ENDPOINT`` a bare string in the other - so the shapes are normalised rather than
    assumed alike. These are the steps whose variables the runner *also* restates inline,
    which is the drift the test suite guards; the judges need no such guard because their
    gate reads the same array this module reads.
    """
    import sys

    smokes_dir = root / "scripts" / "smokes"
    if str(smokes_dir) not in sys.path:
        sys.path.append(str(smokes_dir))

    creds: dict[str, tuple[str, ...]] = {}
    for module_name, step_names in (
        ("langfuse_smoke", ("live:langfuse-smoke", "live:langfuse-sink")),
        ("phoenix_smoke", ("live:phoenix-smoke", "live:phoenix-sink")),
    ):
        try:
            module = __import__(module_name)
        except ImportError as exc:  # pragma: no cover - the smokes ship with the repo
            logger.warning("cannot import %s (%s); its credential row is omitted", module_name, exc)
            continue
        required = getattr(module, "REQUIRED_ENV", None)
        if required is None:
            endpoint = getattr(module, "ENV_ENDPOINT", None)
            required = (endpoint,) if endpoint else ()
        for step in step_names:
            creds[step] = tuple(str(name) for name in required)
    return creds


def _judge_credentials(root: Path) -> dict[str, tuple[str, ...]]:
    """``$liveJudges`` name/env pairs from the runner."""
    if not RUNNER_PATH.is_file():
        return {}
    text = _join_continuations(RUNNER_PATH.read_text(encoding="utf-8"))
    body = _array_blocks(text).get("liveJudges")
    if body is None:
        return {}
    out: dict[str, tuple[str, ...]] = {}
    for entry in _HASH_ENTRY_RE.finditer(body):
        env_match = re.search(r"\benv\s*=\s*@\((?P<env>[^)]*)\)", entry.group(0))
        names = tuple(_QUOTED_RE.findall(env_match.group("env"))) if env_match else ()
        out[entry.group("name")] = names
    return out


def runner_judge_specs() -> dict[str, dict[str, str]]:
    """``$liveJudges`` entries as ``{step name: {type, param, model}}``.

    ``param`` is the judge constructor's model keyword. It is per-entry rather than fixed
    because the judges disagree: two take ``model`` and one takes ``model_id``. Exposed so
    a test can check each declared keyword against the real signature.
    """
    if not RUNNER_PATH.is_file():
        return {}
    body = _array_blocks(_join_continuations(RUNNER_PATH.read_text(encoding="utf-8"))).get("liveJudges")
    if body is None:
        return {}
    specs: dict[str, dict[str, str]] = {}
    for entry in _HASH_ENTRY_RE.finditer(body):
        fields = {key: value for key, value in re.findall(r"\b(type|param)\s*=\s*'([^']+)'", entry.group(0))}
        specs[entry.group("name")] = fields
    return specs


def runner_env_assertions(runner_text: str) -> tuple[tuple[str, ...], ...]:
    """Every ``Test-EnvSet @( ... )`` variable set the runner gates a live step on.

    These are restated inline four times in the runner and again in the Python smokes with
    no guard tying them together - unlike the skip code, which is guarded. Exposed here so
    the test suite can close that gap.
    """
    sets: list[tuple[str, ...]] = []
    for match in re.finditer(r"Test-EnvSet\s+@\((?P<env>[^)]*)\)", runner_text):
        names = tuple(_QUOTED_RE.findall(match.group("env")))
        if names:
            sets.append(names)
    return tuple(sets)


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------


def policy_problems(run: Sequence[RunStep], declared: Sequence[DeclaredStep]) -> list[str]:
    """Reasons this run must not be rendered.

    An empty census is refused outright: a matrix built from nothing would report a clean
    sheet for a run that never happened, which is precisely the false green the runner's
    own ``>0 tests collected`` assertion exists to prevent.
    """
    problems: list[str] = []
    if not run:
        problems.append("the run report contains no steps; a matrix rendered from it would be vacuous")
    known = {step.name for step in declared}
    for step in run:
        if step.name not in known:
            problems.append(
                f"step {step.name!r} appears in the run report but is not declared in "
                f"{RUNNER_PATH.name}; the parser is stale"
            )
    observed_tiers = {step.tier for step in run}
    for tier in sorted(observed_tiers):
        if not any(step.tier == tier for step in declared):
            problems.append(f"tier {tier!r} was observed but no declared step belongs to it")
    return problems


# ---------------------------------------------------------------------------
# Sheet model
# ---------------------------------------------------------------------------

MATRIX_COLUMNS = (
    "Tier",
    "Area",
    "Step",
    "Command",
    "Workdir",
    "Required Credentials",
    "Status",
    "Detail",
    "Duration (ms)",
    "Tests",
    "Failures",
    "Skipped",
    "Evidence",
)

SUMMARY_COLUMNS = ("Metric", "Value")
COVERAGE_COLUMNS = (
    "Unit",
    "Coverage Floor (%)",
    "Floor Anchors",
    "CI Workflows",
    "Suite Step",
    "Suite Status",
    "Tests",
)
CREDENTIAL_COLUMNS = ("Live Step", "Required Env Vars", "Run Outcome")
PROVENANCE_COLUMNS = ("Field", "Value")

#: JUnit stem -> step name is not declared anywhere machine-readable, so it is recovered by
#: matching a suite step's trailing segment against the XML file stems actually present.
_SUITE_PREFIXES = ("suite:", "e2e:")


def _junit_for(step_name: str, junit: Mapping[str, SuiteArtifact]) -> SuiteArtifact | None:
    """Best-effort JUnit lookup for a suite step, matched on the stem the runner chose."""
    if not step_name.startswith(_SUITE_PREFIXES):
        return None
    # The runner names each JUnit file itself, and the stem does not always equal the step
    # tail: `suite:scripts-gate` writes `scripts.xml`, and `e2e:skills+hooks` writes
    # `e2e_journeys.xml`. Try the tail, its filename-safe form, then its leading segment
    # before giving up, so a present count is never reported as absent.
    tail = step_name.split(":", 1)[1]
    for candidate in (tail, tail.replace("+", "_"), safe_step_name(tail), tail.split("-", 1)[0]):
        if candidate in junit:
            return junit[candidate]
    return None


def build_matrix_sheet(
    run: Sequence[RunStep],
    declared: Sequence[DeclaredStep],
    junit: Mapping[str, SuiteArtifact],
    credentials: Mapping[str, tuple[str, ...]],
    report_dir: Path,
    scrub: Callable[[str], str] | None = None,
) -> Sheet:
    """One row per declared step, carrying the observed result where there is one."""
    observed = {step.name: step for step in run}
    rows: list[tuple[str, ...]] = []
    for step in declared:
        result = observed.get(step.name)
        counts = _junit_for(step.name, junit)
        detail = result.detail if result else "not reached in this run"
        rows.append(
            (
                step.tier,
                step.area,
                step.name,
                step.command,
                step.workdir,
                ", ".join(credentials.get(step.name, ())),
                result.status if result else NOT_RUN,
                _scrub(detail, scrub),
                str(result.duration_ms) if result else "",
                str(counts.tests) if counts else "",
                str(counts.failures) if counts else "",
                str(counts.skipped) if counts else "",
                evidence_for(step.name, report_dir) if result else "",
            )
        )
    return Sheet(name="Test Matrix", columns=MATRIX_COLUMNS, rows=tuple(rows))


def build_summary_sheet(run: Sequence[RunStep], declared: Sequence[DeclaredStep]) -> Sheet:
    """Counts by tier and status, plus the declared-vs-observed reconciliation."""
    rows: list[tuple[str, str]] = [
        ("Declared steps", str(len(declared))),
        ("Observed steps", str(len(run))),
        ("Not reached", str(len(declared) - len({s.name for s in run}))),
    ]
    for status in sorted({step.status for step in run}):
        rows.append((f"Status {status}", str(sum(1 for s in run if s.status == status))))
    for tier in sorted({step.tier for step in declared}):
        seen = [s for s in run if s.tier == tier]
        breakdown = ", ".join(
            f"{status} {sum(1 for s in seen if s.status == status)}" for status in sorted({s.status for s in seen})
        )
        rows.append((f"Tier {tier}", breakdown or "not exercised in this run"))
    return Sheet(name="Summary", columns=SUMMARY_COLUMNS, rows=tuple(rows))


def build_coverage_sheet(
    packages: Sequence[PackageFacts],
    run: Sequence[RunStep],
    declared: Sequence[DeclaredStep],
    junit: Mapping[str, SuiteArtifact],
) -> Sheet:
    """Gated unit against the suite step that exercised it in this run."""
    observed = {step.name: step for step in run}
    by_tail = {s.name.split(":", 1)[1]: s.name for s in declared if s.name.startswith(_SUITE_PREFIXES)}
    rows: list[tuple[str, ...]] = []
    for pkg in packages:
        # A unit is matched to its suite step by the step-name tail, then by two fallbacks,
        # each of which exists because a row silently read NOT-RUN on a run that had in fact
        # exercised it. The basename covers units named by path
        # (`experiments/backend-validation` -> `e2e:backend-validation`); the leading-segment
        # match covers a tail that qualifies the unit name (`scripts` -> `suite:scripts-gate`).
        # Exact matches are tried for every unit first, so a qualified match can never steal a
        # step from the unit that owns it outright.
        step_name = (
            by_tail.get(pkg.name)
            or by_tail.get(pkg.name.rsplit("/", 1)[-1])
            or next((full for tail, full in sorted(by_tail.items()) if tail.split("-", 1)[0] == pkg.name), "")
        )
        result = observed.get(step_name) if step_name else None
        counts = _junit_for(step_name, junit) if step_name else None
        rows.append(
            (
                pkg.name,
                str(pkg.floor) if pkg.floor is not None else "",
                "; ".join(pkg.anchors),
                ", ".join(pkg.workflows),
                step_name,
                result.status if result else NOT_RUN,
                str(counts.tests) if counts else "",
            )
        )
    return Sheet(name="Coverage Grid", columns=COVERAGE_COLUMNS, rows=tuple(rows))


def build_credentials_sheet(credentials: Mapping[str, tuple[str, ...]], run: Sequence[RunStep]) -> Sheet:
    """Live steps and the variables that gate them. Names only - never values.

    Deliberately records no "is this variable set here" column. That answer depends on the
    machine doing the rendering, so committing it would make the artifact differ per host
    and defeat the freshness gate - the same reason the coverage matrix never renders
    importorskip outcomes. The step's own status already says whether it ran.
    """
    observed = {step.name: step for step in run}
    rows: list[tuple[str, ...]] = []
    for step_name in sorted(credentials):
        result = observed.get(step_name)
        rows.append((step_name, ", ".join(credentials[step_name]), result.status if result else NOT_RUN))
    return Sheet(name="Credentials", columns=CREDENTIAL_COLUMNS, rows=tuple(rows))


def build_provenance_sheet(prov: Provenance, extra: Mapping[str, str] | None = None) -> Sheet:
    """Run identity and the exact recipe that reproduces this artifact."""
    rows: list[tuple[str, str]] = [
        ("Commit", prov.sha),
        ("Branch", prov.branch),
        ("Generated at (UTC)", prov.generated_at),
        ("Host", prov.host),
        ("Python", prov.python_version),
        ("Runner invocation", prov.runner_invocation),
        ("Regenerate", "python tests/test_e2e_matrix.py --update"),
        ("Policy", "Generated artifact per ADR 0032/0033 - do not edit by hand."),
    ]
    for key in sorted(extra or {}):
        rows.append((key, (extra or {})[key]))
    return Sheet(name="Provenance", columns=PROVENANCE_COLUMNS, rows=tuple(rows))


def _scrub(text: str, scrub: Callable[[str], str] | None) -> str:
    """Apply the caller's redaction callable, if any, to text taken from run output."""
    if scrub is None:
        return text
    return scrub(text)


def build_sheets(
    report_dir: Path = DEFAULT_REPORT_DIR,
    *,
    root: Path = _REPO_ROOT,
    provenance: Provenance,
    scrub: Callable[[str], str] | None = None,
) -> tuple[Sheet, ...]:
    """Assemble every sheet from one run report. Raises :class:`MatrixError` on a policy failure.

    This is the whole pipeline in one call: census, declared inventory, derived facts,
    policy, then the sheet model. Ordering is fixed so the workbook's tabs and the CSV set
    are stable across runs.
    """
    if not RUNNER_PATH.is_file():
        raise MatrixError(f"runner not found at {RUNNER_PATH.as_posix()}")
    runner_text = RUNNER_PATH.read_text(encoding="utf-8")

    run = load_run_steps(report_dir)
    declared = parse_declared_steps(runner_text)
    problems = policy_problems(run, declared)
    if problems:
        raise MatrixError("; ".join(problems))

    junit = load_junit(report_dir)
    credentials = derive_live_credentials(root)
    workflows = derive_workflows(root)
    packages = derive_packages(root, workflows)

    return (
        build_matrix_sheet(run, declared, junit, credentials, report_dir, scrub),
        build_summary_sheet(run, declared),
        build_coverage_sheet(packages, run, declared, junit),
        build_credentials_sheet(credentials, run),
        build_provenance_sheet(provenance),
    )


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

#: Substrings that git's merge driver and the repo's conflict-marker guard treat as
#: conflict markers. The guard reads every decodable tracked file, so a cell that began a
#: line with one of these would fail CI on an artifact that is otherwise correct.
_CONFLICT_PREFIXES = ("<<<<<<<", "=======", ">>>>>>>", "|||||||")


def safe_cell(value: str) -> str:
    """Collapse whitespace and defuse anything that would corrupt the rendered file.

    Newlines are removed because a cell containing one splits a CSV record and a markdown
    row; a leading conflict-marker run is prefixed because the repo-wide guard would
    otherwise reject the committed artifact.
    """
    collapsed = " ".join(value.split())
    if collapsed.startswith(_CONFLICT_PREFIXES):
        collapsed = f"'{collapsed}"
    return collapsed


def render_csv(sheet: Sheet) -> str:
    """A sheet as CSV text with LF endings, independent of the writing platform."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(sheet.columns)
    for row in sheet.rows:
        writer.writerow([safe_cell(cell) for cell in row])
    return buffer.getvalue()


def render_markdown(sheets: Sequence[Sheet], banner: str = GENERATED_BANNER) -> str:
    """The whole matrix as one reviewable markdown document."""
    lines: list[str] = ["<!-- " + banner.replace("\n", "\n     ") + " -->", "", "# End-to-end test matrix", ""]
    for sheet in sheets:
        lines += [f"## {sheet.name}", ""]
        lines += list(sheet.notes) + ([""] if sheet.notes else [])
        lines.append("| " + " | ".join(sheet.columns) + " |")
        lines.append("|" + "|".join("---" for _ in sheet.columns) + "|")
        for row in sheet.rows:
            lines.append("| " + " | ".join(safe_cell(cell).replace("|", "\\|") for cell in row) + " |")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def csv_filename(sheet: Sheet) -> str:
    """Stable, filesystem-safe CSV name for a sheet."""
    return re.sub(r"[^a-z0-9]+", "_", sheet.name.lower()).strip("_") + ".csv"


def write_artifacts(sheets: Sequence[Sheet], out_dir: Path) -> list[Path]:
    """Write the markdown document and one CSV per sheet. Returns the paths written."""
    csv_dir = out_dir / "csv"
    csv_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    doc = out_dir / "e2e-matrix.md"
    doc.write_text(render_markdown(sheets), encoding="utf-8", newline="\n")
    written.append(doc)
    for sheet in sheets:
        path = csv_dir / csv_filename(sheet)
        path.write_text(render_csv(sheet), encoding="utf-8", newline="\n")
        written.append(path)
    logger.info("wrote %d artifact file(s) under %s", len(written), out_dir.as_posix())
    return written


# ---------------------------------------------------------------------------
# Freshness
# ---------------------------------------------------------------------------


def artifact_is_fresh(sheets: Sequence[Sheet], out_dir: Path) -> tuple[bool, str]:
    """(fresh?, rendered markdown). A missing committed document counts as stale."""
    rendered = render_markdown(sheets)
    doc = out_dir / "e2e-matrix.md"
    if not doc.is_file():
        return (False, rendered)
    return (doc.read_text(encoding="utf-8") == rendered, rendered)


def freshness_failure_message(rendered: str, out_dir: Path) -> str:
    """Why the committed artifact is stale, not merely that it is."""
    doc = out_dir / "e2e-matrix.md"
    if not doc.is_file():
        return f"{doc.as_posix()} does not exist - {REGEN_HINT}"
    committed = doc.read_text(encoding="utf-8").splitlines()
    diff = list(
        difflib.unified_diff(
            committed,
            rendered.splitlines(),
            fromfile=f"{doc.name} (committed)",
            tofile=f"{doc.name} (regenerated)",
            lineterm="",
            n=1,
        )
    )
    shown = diff[:MAX_DIFF_LINES]
    if len(diff) > MAX_DIFF_LINES:
        shown.append(f"... {len(diff) - MAX_DIFF_LINES} more diff line(s) truncated")
    return f"{doc.as_posix()} is stale - {REGEN_HINT}\n" + "\n".join(shown)
