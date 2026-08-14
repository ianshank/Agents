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
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent

#: Where ``run_all_e2e.ps1`` writes its report (``$Report``). Gitignored; recreated per run.
DEFAULT_REPORT_DIR = _REPO_ROOT / "artifacts" / "e2e-report"

#: Where the committed artifact lives.
DEFAULT_OUT_DIR = _REPO_ROOT / "docs" / "e2e-matrix"

#: The runner's path relative to a repo root. Every ``derive_*`` helper resolves this
#: against its own ``root`` parameter, so passing a non-default root is honored for the
#: runner file too, not just for the facts derived from it.
RUNNER_RELATIVE_PATH = Path("scripts") / "run_all_e2e.ps1"

#: The runner whose step inventory this matrix mirrors.
RUNNER_PATH = _REPO_ROOT / RUNNER_RELATIVE_PATH

#: PowerShell writes ``summary.json`` with ``Set-Content -Encoding UTF8``, which emits a
#: BOM on Windows PowerShell 5.1. ``json.load`` rejects a BOM under plain utf-8, so every
#: read of a runner-produced file goes through this codec instead.
RUNNER_TEXT_ENCODING = "utf-8-sig"

#: Status recorded for a declared step that the run never reached (tier not selected, or a
#: conditional branch not taken). Deliberately distinct from SKIP, which the runner emits
#: for a step it *did* reach and consciously declined to execute.
NOT_RUN = "NOT-RUN"

#: The runner's own vocabulary for a step it did reach, from ``Add-Result``. This module is
#: their one Python-side owner; nothing else in the engine or the xlsx writer respells them.
STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_SKIP = "SKIP"

#: Name the matrix gives the repository-root package, which is not a workspace member.
ROOT_UNIT_NAME = "root"

#: Tree holding gated units that are deliberately outside the workspace (AGENTS.md).
EXPERIMENTS_DIR_NAME = "experiments"

#: Prefix the runner gives every credential-gated live step.
LIVE_STEP_PREFIX = "live:"

#: Marker used where the runner's own default applies (``$WorkDir = $RepoRoot``).
REPO_ROOT_MARKER = "."

#: Filename of the reviewable rendering inside the output directory.
ARTIFACT_DOC_NAME = "e2e-matrix.md"

#: Filename of the workbook rendering inside the output directory. Not freshness-gated
#: (ADR 0033 §4) but reproducibility is asserted by the test suite; kept beside
#: ``ARTIFACT_DOC_NAME`` since both name the same output directory's two renderings.
WORKBOOK_FILENAME = "e2e-test-matrix.xlsx"

#: Subdirectory holding the per-sheet CSV mirrors.
CSV_DIR_NAME = "csv"

#: Filename the runner writes its per-step results to, inside a report directory.
SUMMARY_FILENAME = "summary.json"

#: Directory holding the runner's smoke scripts, relative to the repo root.
SMOKES_DIR_NAME = "scripts/smokes"

#: Bounded diff emitted when the committed artifact is stale.
MAX_DIFF_LINES = 40

#: The one spelling of the regeneration command; every hint/banner/row that tells a reader
#: how to regenerate the artifact is built from this instead of retyping it.
REGEN_COMMAND = "python tests/test_e2e_matrix.py --update"

REGEN_HINT = f"regenerate and commit: {REGEN_COMMAND}"

GENERATED_BANNER = (
    "GENERATED FILE - do not edit by hand.\n"
    f"Regenerate: {REGEN_COMMAND}\n"
    "Freshness-gated by tests/test_e2e_matrix.py::test_matrix_artifact_is_fresh."
)


class MatrixError(RuntimeError):
    """A derivation or policy failure that must stop the render."""


class MatrixConfigError(MatrixError):
    """The tool could not run at all: a required input is missing or unreadable.

    Separated from :class:`MatrixError` because the CLI maps the two to different exit codes
    (2 = usage/config, 1 = the artifact is wrong). That used to be decided by searching the
    message text for the phrase "no run report", so rewording a sentence silently reclassified
    the failure and contradicted the documented contract.
    """


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
    #: JUnit filename the runner declares for this step, or "" for a step that writes none.
    #: Declared rather than guessed: the stem does not follow from the step name
    #: (``e2e:skills+hooks`` writes ``e2e_journeys.xml``), so guessing left that step's
    #: Tests/Failures/Skipped cells blank in a committed artifact.
    junit: str = ""

    @property
    def area(self) -> str:
        """The step-name prefix (``suite``, ``cli``, ``live``, ...); the whole name if bare."""
        return self.name.split(":", 1)[0] if ":" in self.name else self.name

    @property
    def tail(self) -> str:
        """The step-name suffix after the first ``:``; empty for a bare name.

        Guards the same split ``.area`` guards. An earlier unguarded
        ``name.split(":", 1)[1]`` at a coverage-sheet lookup site raised ``IndexError`` for
        any declared step whose name has no colon -- safe only because every step name in
        the real runner happens to contain one.
        """
        return self.name.split(":", 1)[1] if ":" in self.name else ""


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
    path = report_dir / SUMMARY_FILENAME
    if not path.is_file():
        raise MatrixConfigError(f"no run report at {path.as_posix()} - run scripts/run_all_e2e.ps1 first")
    try:
        payload = json.loads(path.read_text(encoding=RUNNER_TEXT_ENCODING))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        # UnicodeDecodeError is a ValueError, not an OSError, and was previously uncaught
        # here -- a byte the encoding can't decode (e.g. a smart quote saved as cp1252 by an
        # editor on the Windows host that runs the harness) crashed with a raw traceback
        # instead of the documented config-error contract.
        raise MatrixConfigError(f"cannot read {path.as_posix()}: {exc}") from exc

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
        # Matched by local tag name, not `root.iter("testsuite")`: ElementTree's tag search
        # is exact-string, so a namespaced document (`<testsuites xmlns="...">`) whose real
        # tag is `{uri}testsuite` never matches and the file silently counts as zero tests --
        # a specific, false number, worse than the blank a genuinely-absent file gets.
        suites = [elem for elem in root.iter() if elem.tag.rsplit("}", 1)[-1] == "testsuite"]
        if not suites:
            logger.warning("no <testsuite> element found in %s; counts omitted", path.name)
            continue
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
    r"(?P<verb>Invoke-PytestStep|Invoke-CmdStep|Add-Result)\s+'(?P<tier>[A-Z]+)'\s+'(?P<name>[^']+)'"
)

#: Only this verb's third trailing positional is a JUnit path. `Invoke-CmdStep`'s third
#: positional is `SkipCodes`, an inline `@(...)` array that the positional-token regex
#: never matches -- safe by accident until a bare-variable `SkipCodes` argument appeared.
_JUNIT_BEARING_VERB = "Invoke-PytestStep"

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


_QUOTED_RE = re.compile(r"'([^']*)'")

# `Join-Path $RepoRoot 'agent-core'` and friends: keep the human-meaningful tail.
_JOIN_PATH_RE = re.compile(r"Join-Path\s+\$\w+\s+'(?P<tail>[^']+)'")


def _join_continuations(text: str) -> str:
    """Fold PowerShell backtick line-continuations so one logical call is one line."""
    return re.sub(r"`[ \t]*\r?\n[ \t]*", " ", text.replace("\r\n", "\n"))


def _balanced_args_span(text: str, start: int) -> tuple[str, int] | None:
    """``(inner text, index just past the close)`` of the first ``@( ... )`` at or after *start*.

    A regex cannot do this. PowerShell keeps an expression open inside parentheses, so an
    argument array is routinely written across several lines with no backtick continuation
    -- and a ``@\\([^)]*\\)`` pattern stops at the first inner ``)`` anyway. Reading 57% of
    the runner's steps as "no command" is what that costs, so the parens are matched.

    The end index is returned because the tokens that follow the array are themselves data:
    ``Invoke-PytestStep`` takes ``WorkDir`` and ``Junit`` positionally right after it.
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
                return (text[open_at + 2 : index], index + 1)
    return None


def _balanced_args(text: str, start: int) -> str | None:
    """Inner text of the first ``@( ... )`` at or after *start*."""
    span = _balanced_args_span(text, start)
    return span[0] if span is not None else None


#: A positional argument that is either a quoted literal or a bare ``$variable``.
_POSITIONAL_TOKEN_RE = re.compile(r"[ \t]+(?P<tok>'[^']*'|\$\w+)")

#: The runner's own name for the repository root, used as the default working directory.
_REPO_ROOT_VARIABLE = "RepoRoot"


def _resolve_path_literal(text: str, token: str) -> str:
    """A positional path argument as a plain string.

    ``'literal'`` resolves to itself, ``$RepoRoot`` to the repo-root marker, and any other
    ``$variable`` to the last quoted literal of its assignment -- which covers the runner's
    ``$x = Join-Path $Report 'name.xml'`` idiom. Unresolvable tokens yield "" rather than a
    guess, because a wrong directory in the matrix is worse than a blank one.
    """
    if token.startswith("'"):
        return token.strip("'")
    variable = token.lstrip("$")
    if variable == _REPO_ROOT_VARIABLE:
        return REPO_ROOT_MARKER
    match = re.search(rf"\${re.escape(variable)}\s*=\s*(?P<rhs>[^\n]+)", text)
    if match is None:
        return ""
    # Only the runner's own `Join-Path <base> 'name'` idiom is resolved. Taking "the last
    # quoted literal on the line" would happily turn
    # `[IO.Path]::Combine($entDir, 'tests', 'integration')` into the directory
    # "integration" -- inventing a path that does not exist. An unresolved token yields ""
    # so the cell is blank instead of confidently wrong.
    joined = re.search(r"Join-Path\s+\S+\s+'(?P<tail>[^']+)'", match.group("rhs"))
    if joined is not None:
        return joined.group("tail")
    bare = re.fullmatch(r"'(?P<value>[^']*)'\s*", match.group("rhs"))
    return bare.group("value") if bare else ""


def _trailing_positionals(text: str, after: int, limit: int) -> list[str]:
    """Up to *limit* positional tokens immediately following a step call's argument array."""
    tokens: list[str] = []
    cursor = after
    while len(tokens) < limit:
        match = _POSITIONAL_TOKEN_RE.match(text, cursor)
        if match is None:
            break
        tokens.append(match.group("tok"))
        cursor = match.end()
    return tokens


def _resolve_array_literal(text: str, variable: str) -> str | None:
    """Inner text of ``$<variable> = @( ... )``, wherever it is indented."""
    match = re.search(rf"\${re.escape(variable)}\s*=\s*(?=@\()", text)
    return _balanced_args(text, match.end()) if match else None


#: One argument of a PowerShell array: a single-quoted literal, a double-quoted literal, or a
#: bare ``$variable``. Variables are captured too -- dropping them silently produced command
#: lines that looked complete and were not, e.g. ``compare --config --offline`` with the
#: config path (a ``$compareYaml`` variable) missing. A reader copying that would run the
#: wrong command; rendering the variable name verbatim is honest about what the runner passes.
_ARG_TOKEN_RE = re.compile(r"'([^']*)'|\"([^\"]*)\"|(\$\w+)")


def _render_command(args_text: str | None) -> str:
    """Render a PowerShell argument array as a readable ``python ...`` command line."""
    if args_text is None:
        return ""
    tokens = [
        next(group for group in match.groups() if group is not None) for match in _ARG_TOKEN_RE.finditer(args_text)
    ]
    if not tokens:
        return ""
    return "python " + " ".join(tokens)


#: Positional arguments `Invoke-PytestStep` accepts after its argument array: WorkDir, Junit.
_TRAILING_POSITIONAL_LIMIT = 2


def _call_details(text: str, after: int, verb: str) -> dict[str, str]:
    """Command, working directory and JUnit path for a step call, all read from the call site.

    The array must be adjacent to the step name (see :func:`_command_from`); the first
    positional argument that follows it is the runner's ``WorkDir`` for every verb. The
    *second* positional differs by verb: ``Invoke-PytestStep``'s is ``Junit``, but
    ``Invoke-CmdStep``'s is ``SkipCodes`` -- reading it as a JUnit path was safe only by
    accident, because every real ``Invoke-CmdStep`` call passes ``SkipCodes`` as an inline
    ``@(...)`` array that the positional-token regex does not match. A call that omits the
    positionals genuinely runs at the repo root and writes no JUnit, which is the function's
    own documented default -- so the fallback here is a fact, not a guess.
    """
    span = _balanced_args_span(text, after) if re.match(r"\s*(?=@\()", text[after:]) else None
    if span is None:
        return {"command": "", "workdir": REPO_ROOT_MARKER, "junit": ""}
    args_text, end = span
    tokens = _trailing_positionals(text, end, _TRAILING_POSITIONAL_LIMIT)
    resolved = [_resolve_path_literal(text, token) for token in tokens]
    junit = resolved[1] if verb == _JUNIT_BEARING_VERB and len(resolved) > 1 else ""
    return {
        "command": _render_command(args_text),
        "workdir": resolved[0] if resolved else REPO_ROOT_MARKER,
        "junit": junit,
    }


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
                tier=existing.tier,
                name=existing.name,
                command=step.command,
                workdir=step.workdir,
                junit=step.junit,
            )

    for match in _LITERAL_STEP_RE.finditer(text):
        name = match.group("name")
        record(
            DeclaredStep(tier=match.group("tier"), name=name, **_call_details(text, match.end(), match.group("verb")))
        )

    for match in _VARIABLE_STEP_RE.finditer(text):
        collection = bindings.get(match.group("item"))
        body = blocks.get(collection or "")
        if body is None:
            logger.warning("cannot resolve $%s.name to an array literal; steps may be missing", match.group("item"))
            continue
        if not body.strip():
            logger.warning(
                "$%s is an empty array literal; no steps recorded for $%s.name", collection, match.group("item")
            )
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
                    junit=_junit_from(entry.group(0)),
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


# Known, deliberately deferred parser limitations (none occur in the real runner today, so
# hardening against them would be a lexer with no live defect to guard):
#   * A nested hashtable inside a ``$suites``/``$liveJudges`` entry (a value that is itself
#     ``@{ ... }``) would confuse ``_HASH_ENTRY_RE``'s field matching.
#   * An unbalanced parenthesis inside a single-quoted string argument would desynchronize
#     ``_balanced_args_span``.
#   * PowerShell's ``''`` escape for a literal single quote inside a quoted string is not
#     unescaped by ``_QUOTED_RE``.
#   * A double-quoted hashtable field name (``"name" = 'x'``) is not matched; every real
#     entry uses bare or single-quoted keys.
#   * A pipeline-closed array block (``@( ... ) | Sort-Object``) immediately followed by
#     another ``@( ... )`` could let ``_ARRAY_BLOCK_RE`` swallow the second block.


_HASH_XML_RE = re.compile(r"\bxml\s*=\s*'(?P<xml>[^']+)'")


def _junit_from(hash_text: str) -> str:
    """JUnit filename declared by a ``$suites`` entry (``xml = 'root.xml'``)."""
    match = _HASH_XML_RE.search(hash_text)
    return match.group("xml") if match else ""


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
    if facts.skipped:  # pragma: no cover - needs a member dir whose name is not Make-safe
        logger.warning("workspace detector skipped non-safe member name(s): %s", ", ".join(facts.skipped))
    return tuple(str(member) for member in facts.members)


def _read_text_or_none(path: Path) -> str | None:
    """UTF-8 text of *path*, or ``None`` if it is missing or undecodable.

    Every derivation in this module treats an absent input file as "nothing to derive" and
    already handled that gracefully; a file that exists but can't be decoded (a byte the
    Windows host that runs the harness saved in cp1252, say) previously crashed uncaught at
    each read site instead of degrading the same way. One helper, one behaviour, and it
    collapses what used to be a repeated ``if not path.is_file(): return X`` guard at every
    call site into a single check.
    """
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("cannot read %s (%s); treating it as absent", path.as_posix(), exc)
        return None


def makefile_check_members(root: Path) -> tuple[str, ...]:
    """Members named by the Makefile's ``check-all`` prerequisites.

    A second, independent anchor for the member list. The two are asserted equal by the
    test suite, which is how a Makefile regenerated against a changed tree gets noticed.
    """
    text = _read_text_or_none(root / "Makefile")
    if text is None:
        return ()
    for line in text.splitlines():
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
    text = _read_text_or_none(path)
    if text is None:
        return None
    section = re.search(r"^\[tool\.coverage\.report\](?P<body>.*?)(?=^\[|\Z)", text, re.MULTILINE | re.DOTALL)
    if section is None:
        return None
    value = re.search(r"^\s*fail_under\s*=\s*\"?(?P<n>\d+)", section.group("body"), re.MULTILINE)
    return int(value.group("n")) if value else None


def _floor_from_gate_script(path: Path) -> int | None:
    """``COV_FAIL_UNDER="${COV_FAIL_UNDER:-N}"`` from a generated quality-gate script."""
    text = _read_text_or_none(path)
    if text is None:
        return None
    match = re.search(r"COV_FAIL_UNDER=\"\$\{COV_FAIL_UNDER:-(?P<n>\d+)\}\"", text)
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
    roots: list[tuple[str, Path]] = [(ROOT_UNIT_NAME, root)]
    roots += [(name, root / name) for name in derive_members(root)]
    # Units that are gated but are not workspace members: discovered by looking for the
    # marker every gated unit carries (its own pyproject) under the experiments tree, rather
    # than naming `experiments/backend-validation` here. A second experiment acquiring a
    # coverage floor then appears on its own, at any depth -- not just a direct child of
    # `experiments/`, since a manifest one level deeper than today's single example would
    # otherwise be silently absent from the Coverage Grid.
    roots += [
        (manifest.parent.relative_to(root).as_posix(), manifest.parent)
        for manifest in sorted((root / EXPERIMENTS_DIR_NAME).rglob("pyproject.toml"))
    ]

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

    Derived from each workflow's ``working-directory:`` values. A workflow with none at all
    runs at the repo root by GitHub Actions' own default -- this used to require the text to
    also mention the shared quality-gate action, an incidental heuristic from when every
    bare-root workflow happened to use it. ``quality-gates.yml`` has inline steps and never
    matched, so it was invisible in the Coverage Grid despite being the workflow that runs
    this very generator's own coverage floor.

    Known limitation, not fixed here: a unit gated only by a *named step* inside an otherwise
    working-directory-free workflow (e.g. the ``scripts`` coverage step in
    ``quality-gates.yml``) is not attributed to that unit specifically -- only to
    :data:`ROOT_UNIT_NAME`. Deeper per-step workflow-body scanning is out of scope; see
    ``docs/e2e-matrix/README.md``.
    """
    mapping: dict[str, set[str]] = {}
    workflow_dir = root / ".github" / "workflows"
    if not workflow_dir.is_dir():
        return {}
    for path in sorted({*workflow_dir.glob("*.yml"), *workflow_dir.glob("*.yaml")}):
        text = _read_text_or_none(path)
        if text is None:
            continue
        dirs = {m.group("d").strip().strip("\"'") for m in re.finditer(r"working-directory:\s*(?P<d>\S+)", text)}
        if not dirs:
            dirs = {ROOT_UNIT_NAME}
        for directory in dirs:
            key = ROOT_UNIT_NAME if directory in {REPO_ROOT_MARKER, ROOT_UNIT_NAME} else directory
            mapping.setdefault(key, set()).add(path.name)
    return {key: tuple(sorted(names)) for key, names in mapping.items()}


#: A live step gated by a literal variable set, e.g.
#: ``elseif (Test-EnvSet @('LANGFUSE_SECRET_KEY', ...)) { ... 'live:langfuse-smoke' ... }``.
_ENV_GATE_RE = re.compile(r"Test-EnvSet\s+@\((?P<env>[^)]*)\)")

#: Smoke scripts a step invokes, e.g. ``scripts/smokes/langfuse_smoke.py``.
_SMOKE_SCRIPT_RE = re.compile(re.escape(SMOKES_DIR_NAME) + r"/(?P<module>\w+)\.py")


def derive_live_credentials(root: Path = _REPO_ROOT) -> dict[str, tuple[str, ...]]:
    """Required environment variables for every live step, from the runner's own gates.

    The runner decides whether a live step runs, so the runner is the authority on what
    gates it. Each literal ``Test-EnvSet @(...)`` guards exactly one step, and the judges
    gate on ``$liveJudges[].env``; between them every live step is covered.

    This used to be a hand-written table mapping smoke modules to step names, which had to
    be edited by hand whenever a live step was added or renamed -- the "literal claiming
    completeness unchecked" shape this repo has closed three times elsewhere. The smokes'
    own ``REQUIRED_ENV`` is still read, but only as the cross-language drift guard in
    :func:`smoke_credentials`, not as the source of the matrix.
    """
    creds = runner_env_gates(root)
    creds.update(_judge_credentials(root / RUNNER_RELATIVE_PATH))
    return creds


def runner_env_gates(root: Path = _REPO_ROOT) -> dict[str, tuple[str, ...]]:
    """Map each literal-gated live step to the variable set guarding it.

    Attribution is by nearest preceding gate: the runner writes
    ``Test-EnvSet @(...)`` immediately above the step it guards, and every occurrence in
    the file follows that shape. A step with no preceding literal gate (the judges, which
    gate on a variable) is simply absent, and picked up from ``$liveJudges`` instead.
    """
    raw = _read_text_or_none(root / RUNNER_RELATIVE_PATH)
    if raw is None:
        return {}
    text = _join_continuations(raw)
    gates = [(m.start(), tuple(_QUOTED_RE.findall(m.group("env")))) for m in _ENV_GATE_RE.finditer(text)]
    gates = [(pos, names) for pos, names in gates if names]

    out: dict[str, tuple[str, ...]] = {}
    for match in _LITERAL_STEP_RE.finditer(text):
        name = match.group("name")
        preceding = [names for pos, names in gates if pos < match.start()]
        if preceding and name not in out:
            out[name] = preceding[-1]
    # Only live steps are gated on credentials; a non-live step that merely happens to sit
    # after a gate must not inherit it.
    return {name: names for name, names in out.items() if name.startswith(LIVE_STEP_PREFIX)}


def smoke_credentials(root: Path = _REPO_ROOT) -> dict[str, tuple[str, ...]]:
    """Variables each smoke script declares it needs, keyed by the step that invokes it.

    Which module belongs to which step is derived from the step's own command
    (``scripts/smokes/<module>.py``), so adding a smoke needs no edit here. The two smokes
    spell the requirement differently - ``REQUIRED_ENV`` is a tuple in one, ``ENV_ENDPOINT``
    a bare string in the other - so the shapes are normalised rather than assumed alike.

    Used only to cross-check the runner's inline gates, which restate the same variable
    names with nothing tying the two together.
    """
    import sys

    smokes_dir = root / SMOKES_DIR_NAME
    if str(smokes_dir) not in sys.path:
        sys.path.append(str(smokes_dir))

    raw = _read_text_or_none(root / RUNNER_RELATIVE_PATH)
    if raw is None:
        return {}
    creds: dict[str, tuple[str, ...]] = {}
    for step in parse_declared_steps(raw):
        found = _SMOKE_SCRIPT_RE.search(step.command)
        if found is None:
            continue
        try:
            module = __import__(found.group("module"))
        except ImportError as exc:  # pragma: no cover - the smokes ship with the repo
            logger.warning("cannot import %s (%s); its credential row is omitted", found.group("module"), exc)
            continue
        required = getattr(module, "REQUIRED_ENV", None)
        if required is None:
            endpoint = getattr(module, "ENV_ENDPOINT", None)
            required = (endpoint,) if endpoint else ()
        creds[step.name] = tuple(str(name) for name in required)
    return creds


#: The runner's own name for the array of live-judge declarations.
LIVE_JUDGES_ARRAY_NAME = "liveJudges"


def _live_judge_entries(runner_path: Path) -> list[re.Match[str]]:
    """Raw ``$liveJudges`` hashtable-entry matches, or ``[]`` if the runner/array is absent.

    Shared by :func:`_judge_credentials` and :func:`runner_judge_specs`, which used to be
    the same six-line body (file check, join continuations, locate the array, iterate
    entries) differing only in which fields each pulled out of the matched text.
    """
    raw = _read_text_or_none(runner_path)
    if raw is None:
        return []
    body = _array_blocks(_join_continuations(raw)).get(LIVE_JUDGES_ARRAY_NAME)
    if body is None:
        return []
    return list(_HASH_ENTRY_RE.finditer(body))


def _judge_credentials(runner_path: Path = RUNNER_PATH) -> dict[str, tuple[str, ...]]:
    """``$liveJudges`` name/env pairs from the runner."""
    out: dict[str, tuple[str, ...]] = {}
    for entry in _live_judge_entries(runner_path):
        env_match = re.search(r"\benv\s*=\s*@\((?P<env>[^)]*)\)", entry.group(0))
        names = tuple(_QUOTED_RE.findall(env_match.group("env"))) if env_match else ()
        out[entry.group("name")] = names
    return out


def runner_judge_specs(runner_path: Path = RUNNER_PATH) -> dict[str, dict[str, str]]:
    """``$liveJudges`` entries as ``{step name: {type, param}}``.

    ``param`` is the judge constructor's model keyword. It is per-entry rather than fixed
    because the judges disagree: two take ``model`` and one takes ``model_id``. Exposed so
    a test can check each declared keyword against the real signature.
    """
    specs: dict[str, dict[str, str]] = {}
    for entry in _live_judge_entries(runner_path):
        fields = {key: value for key, value in re.findall(r"\b(type|param)\s*=\s*'([^']+)'", entry.group(0))}
        specs[entry.group("name")] = fields
    return specs


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

    seen_names: set[str] = set()
    for step in run:
        if step.name in seen_names:
            problems.append(
                f"step {step.name!r} appears more than once in the run report; the Summary "
                f"sheet's counts would silently stop matching the Test Matrix rows"
            )
        seen_names.add(step.name)

    by_name = {step.name: step for step in declared}
    for step in run:
        declared_step = by_name.get(step.name)
        if declared_step is None:
            problems.append(
                f"step {step.name!r} appears in the run report but is not declared in "
                f"{RUNNER_PATH.name}; the parser is stale"
            )
        elif declared_step.tier != step.tier:
            problems.append(
                f"step {step.name!r} was observed under tier {step.tier!r} but is declared "
                f"under tier {declared_step.tier!r}; the Test Matrix and Summary sheets "
                f"would disagree about which tier ran it"
            )

    observed_tiers = {step.tier for step in run}
    for tier in sorted(observed_tiers):
        if not any(step.tier == tier for step in declared):
            problems.append(f"tier {tier!r} was observed but no declared step belongs to it")
    return problems


# ---------------------------------------------------------------------------
# Sheet model
# ---------------------------------------------------------------------------

#: Header of the column carrying a step's outcome; the workbook colours by it.
STATUS_COLUMN = "Status"

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
    "Errors",
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


def _junit_for(step: DeclaredStep, junit: Mapping[str, SuiteArtifact]) -> SuiteArtifact | None:
    """Counters for a step, looked up by the JUnit filename the runner declares for it.

    Previously the stem was guessed from the step name through a ladder of candidate
    spellings. That silently failed for ``e2e:skills+hooks`` (whose file is
    ``e2e_journeys.xml``), shipping blank Tests/Failures/Skipped cells in a committed
    artifact, and resolved ``suite:scripts-gate`` only by accident. The runner names the
    file at every call site, so there is nothing to guess.
    """
    if not step.junit:
        return None
    return junit.get(Path(step.junit).stem)


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
        counts = _junit_for(step, junit)
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
                str(counts.errors) if counts else "",
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
    by_step = {s.name: s for s in declared}
    by_tail = {s.tail: s.name for s in declared if s.junit and s.tail}
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
            or next(
                (full for tail, full in sorted(by_tail.items()) if tail.startswith(pkg.name + "-")),
                "",
            )
        )
        result = observed.get(step_name) if step_name else None
        counts = _junit_for(by_step[step_name], junit) if step_name in by_step else None
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


def build_provenance_sheet(prov: Provenance) -> Sheet:
    """Run identity and the exact recipe that reproduces this artifact."""
    rows: list[tuple[str, str]] = [
        ("Commit", prov.sha),
        ("Branch", prov.branch),
        ("Generated at (UTC)", prov.generated_at),
        ("Host", prov.host),
        ("Python", prov.python_version),
        ("Runner invocation", prov.runner_invocation),
        ("Regenerate", REGEN_COMMAND),
        ("Policy", "Generated artifact per ADR 0032/0033 - do not edit by hand."),
    ]
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
    runner_path = root / RUNNER_RELATIVE_PATH
    runner_text = _read_text_or_none(runner_path)
    if runner_text is None:
        raise MatrixConfigError(f"runner not found at {runner_path.as_posix()}")

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

#: Control characters other than whitespace. `str.split()` handles tabs and newlines but
#: leaves e.g. NUL or ESC in place, and the XML spec forbids them in a worksheet cell, so a
#: single stray byte in a step's output would crash the workbook writer on an otherwise
#: perfectly good run.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def safe_cell(value: str) -> str:
    """Collapse whitespace and defuse anything that would corrupt the rendered file.

    Newlines are removed because a cell containing one splits a CSV record and a markdown
    row; a leading conflict-marker run is prefixed because the repo-wide guard would
    otherwise reject the committed artifact.
    """
    collapsed = " ".join(_CONTROL_CHARS_RE.sub(" ", value).split())
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
    csv_dir = out_dir / CSV_DIR_NAME
    csv_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    doc = out_dir / ARTIFACT_DOC_NAME
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


#: Heading of the section excluded from the staleness comparison (see :func:`comparable`).
PROVENANCE_SHEET_NAME = "Provenance"


def comparable(document: str) -> str:
    """The part of the artifact whose staleness is meaningful.

    Everything above the Provenance section. That section records *when and where the
    artifact was generated*, including the commit SHA at generation time -- and committing
    the artifact necessarily creates a new commit, so that SHA is one behind the instant it
    lands. A gate that compared it could never be green on the very commit carrying the
    artifact, which is worse than no gate: a check that is always red teaches people to
    ignore it. Provenance is metadata about the generation event, not content derived from
    the run, so staleness is judged on the derived content alone.
    """
    return document.split(f"\n## {PROVENANCE_SHEET_NAME}\n", 1)[0]


def stale_csv_mirrors(sheets: Sequence[Sheet], out_dir: Path) -> list[str]:
    """CSV mirrors whose committed bytes differ from what the sheets render to.

    The markdown was previously the only gated output, so a CSV could drift from the run it
    claims to describe and still be reported fresh. The CSVs are the diffable rendering that
    review actually reads, which makes an ungated CSV the worst of the three to let rot.

    Also flags an *orphan*: a CSV on disk with no corresponding current sheet, e.g. left
    behind by a sheet rename. Checking only the current sheets' own paths, as the original
    version of this function did, can never notice a file it never looks for.
    """
    csv_dir = out_dir / CSV_DIR_NAME
    stale: list[str] = []
    expected_names: set[str] = set()
    for sheet in sheets:
        # The Provenance exemption has to hold here too. Gating its CSV would reintroduce
        # exactly the defect `comparable()` exists to prevent: the recorded SHA is one commit
        # behind the moment the artifact is committed, so the check could never be green on
        # the commit that carries it.
        if sheet.name == PROVENANCE_SHEET_NAME:
            continue
        name = csv_filename(sheet)
        expected_names.add(name)
        path = csv_dir / name
        if not path.is_file() or path.read_text(encoding="utf-8") != render_csv(sheet):
            stale.append(path.name)
    if csv_dir.is_dir():
        # The Provenance CSV is exempt above even when a caller passes that sheet, so it must
        # be exempt from the orphan sweep too, or every fresh check would flag it as orphaned.
        provenance_name = csv_filename(Sheet(name=PROVENANCE_SHEET_NAME, columns=()))
        orphans = {p.name for p in csv_dir.glob("*.csv")} - expected_names - {provenance_name}
        stale.extend(orphans)
    return sorted(stale)


def artifact_is_fresh(sheets: Sequence[Sheet], out_dir: Path) -> tuple[bool, str]:
    """(fresh?, rendered markdown). A missing committed document counts as stale.

    Covers the markdown *and* every CSV mirror. The workbook is excluded on purpose: it is a
    presentation rendering of the same sheet model, it is only writable where the optional
    extra is installed, and byte-comparing it would make the gate fail for anyone without
    openpyxl. Its own reproducibility is asserted by the test suite instead.
    """
    rendered = render_markdown(sheets)
    doc = out_dir / ARTIFACT_DOC_NAME
    if not doc.is_file():
        return (False, rendered)
    if comparable(doc.read_text(encoding="utf-8")) != comparable(rendered):
        return (False, rendered)
    return (not stale_csv_mirrors(sheets, out_dir), rendered)


def freshness_failure_message(rendered: str, out_dir: Path, sheets: Sequence[Sheet]) -> str:
    """Why the committed artifact is stale, not merely that it is.

    ``sheets`` has no default: a caller that forgets it silently gets "the markdown is
    stale" for what may actually be a stale *CSV* mirror only, since ``stale_csv_mirrors``
    needs the current sheet set to know which CSVs should exist. A signature that invites
    the wrong call is itself the defect an earlier ``sheets=()`` default here caused.
    """
    doc = out_dir / ARTIFACT_DOC_NAME
    if not doc.is_file():
        return f"{doc.as_posix()} does not exist - {REGEN_HINT}"
    stale_csvs = stale_csv_mirrors(sheets, out_dir) if sheets else []
    committed = comparable(doc.read_text(encoding="utf-8")).splitlines()
    diff = list(
        difflib.unified_diff(
            committed,
            comparable(rendered).splitlines(),
            fromfile=f"{doc.name} (committed)",
            tofile=f"{doc.name} (regenerated)",
            lineterm="",
            n=1,
        )
    )
    shown = diff[:MAX_DIFF_LINES]
    if len(diff) > MAX_DIFF_LINES:
        shown.append(f"... {len(diff) - MAX_DIFF_LINES} more diff line(s) truncated")
    if not diff and stale_csvs:
        return f"{out_dir.as_posix()} has stale CSV mirror(s): {', '.join(stale_csvs)} - {REGEN_HINT}"
    return f"{doc.as_posix()} is stale - {REGEN_HINT}\n" + "\n".join(shown)
