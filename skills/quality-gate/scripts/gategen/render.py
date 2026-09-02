"""Render :class:`GateFacts` into a deterministic, ShellCheck-clean quality-gate script.

The emitted ``quality-gate.sh`` is the single source of truth for a project's checks: the
same script runs locally and in CI, so the two cannot drift. Output is byte-stable (no
timestamps) and uses ``set -euo pipefail`` so any failing step aborts with a non-zero exit.
Only the checks the project actually supports are emitted — nothing is fabricated.

Hand-extension seam: everything above :data:`MARKER` is generator-owned (regenerated and
freshness-checked); everything below it is hand-maintained and preserved across
regeneration. Extensions define ``do_extra()`` below the marker; ``do_all`` invokes it when
present, so package-specific steps join the gate without the generator guessing them.
"""

from __future__ import annotations

import shlex

from .model import GateFacts

# Boundary between generator-owned content (above, prefix-compared by --check and rewritten
# on regeneration) and hand-maintained content (below, preserved verbatim).
MARKER = "# --- hand-maintained extensions below; the generator manages everything above this line ---"

# printf keeps the variable out of the format string (ShellCheck-clean, no SC2059).
_LOG = "log() { printf '\\n\\033[1m[quality-gate] %s\\033[0m\\n' \"$1\"; }"

_ORDER = ("lint", "typecheck", "test", "coverage")

# Default tail below the marker on a fresh render: documents the seam, then dispatches.
# ``main "$@"`` deliberately lives below the marker so hand extensions (function
# definitions) are parsed before dispatch; deleting it is a visible, diffable choice.
_DEFAULT_TAIL = (
    "# Define extra gate steps here as do_extra() { ... }; `all` runs them automatically.",
    "",
    'main "$@"',
)


def _sh_escape(value: str) -> str:
    r"""Escape a value for safe literal use inside a bash double-quoted string.

    A detected value containing ``$``, a backtick, ``"`` or ``\`` would otherwise trigger
    parameter/command substitution or break the string. Backslash is escaped first so the
    other escapes are not doubled.
    """
    out = value.replace("\\", "\\\\")
    for ch in ("$", "`", '"'):
        out = out.replace(ch, "\\" + ch)
    return out


def _quoted(paths: tuple[str, ...]) -> str:
    """Space-joined, double-quoted, escaped path literals for a command line."""
    return " ".join(f'"{_sh_escape(p)}"' for p in paths)


def split_at_marker(text: str) -> tuple[str, str]:
    """Split script text into (generator-owned prefix incl. marker line, hand tail).

    The prefix ends with the marker line's line terminator — ``\\r\\n`` is consumed as a
    unit so a CRLF file (e.g. edited on Windows) never yields a tail starting with a stray
    ``\\r`` (which would corrupt preservation into mixed line endings). Text without a
    marker is all prefix (older 1.0.x artifacts): callers treat that as "no hand region to
    preserve".
    """
    idx = text.find(MARKER)
    if idx < 0:
        return text, ""
    end = idx + len(MARKER)
    if text.startswith("\r\n", end):
        end += 2
    elif end < len(text) and text[end] == "\n":
        end += 1
    return text[:end], text[end:]


def _typecheck_env_form(facts: GateFacts) -> bool:
    """Single source of truth for 'typecheck uses the $TYPECHECK_PATHS env form'.

    Both the variable definition (:func:`_variables`) and the command that references it
    (:func:`_typecheck_commands`) consult THIS predicate — if they disagreed, the generated
    script would reference an undefined variable and abort under ``set -u``.
    """
    return len(facts.typecheck_paths) == 1


def _ignored_override_notice(var: str) -> str:
    """A shell line that warns when a generation-time-literal step ignores an env override.

    Multi-path/multi-source steps hardcode their targets (the quoted env var cannot hold a
    list), so an exported single-value override would otherwise be swallowed silently. The
    coverage gate ALSO uses this unconditionally (single- or multi-source alike) for
    ``COVERAGE_SOURCE`` and ``COV_FAIL_UNDER``: both are gate-integrity values, not a debug
    affordance, so neither is ever a live env override, regardless of how many sources exist.
    """
    return f'if [ -n "${{{var}:-}}" ]; then echo "quality-gate: {var} is ignored; targets are fixed at generation time" >&2; fi'


def _warn_then_unset_guard(var: str, reason: str) -> list[str]:
    """Shared shell-line builder for a "live env var read directly by the invoked tool"
    guard: warn to stderr if it is set, then unset it before the tool runs.

    Both ``_pytest_addopts_guard`` and ``_coverage_rcfile_guard`` need this exact shape for
    the same underlying reason: unlike ``COVERAGE_SOURCE``/``COV_FAIL_UNDER`` (values THIS
    generator itself interpolates into the command line, so simply never referencing the env
    var is enough to neutralize an override), pytest and coverage.py each read their
    respective var directly from the process environment — a warning alone would not stop it
    from taking effect, so the guard also unsets it. Factored here once the two call sites
    were byte-identical except for the var name and the reason clause, so the shape can no
    longer drift between them the way the two would-be independent copies once could have.
    """
    return [
        f'if [ -n "${{{var}:-}}" ]; then echo "quality-gate: {var} is ignored; {reason}" >&2; fi',
        f"unset {var}",
    ]


def _pytest_addopts_guard() -> list[str]:
    """Warn-then-clear guard so a live ``PYTEST_ADDOPTS`` cannot weaken a pytest gate step.

    Pytest reads ``PYTEST_ADDOPTS`` directly from its own environment, so a coverage-weakening
    flag (``--no-cov``, ``-k``, ``--override-ini``, ...) would otherwise take effect silently.
    Emitted ahead of every pytest invocation the gate makes (``do_test`` and ``do_coverage``)
    — a gate stage has no opt-out.
    """
    return _warn_then_unset_guard("PYTEST_ADDOPTS", "this stage is a gate and has no opt-out")


def _coverage_rcfile_guard() -> list[str]:
    """Warn-then-clear guard so a live ``COVERAGE_RCFILE`` cannot widen the coverage config.

    coverage.py reads ``COVERAGE_RCFILE`` directly from its own environment, so a pointed-at
    rc file (a broad ``exclude_lines``/``omit``, or a ``fail_under=0``) would otherwise take
    effect silently. ``_coverage_command`` already passes an explicit ``--cov-config=``
    literal, which coverage.py prioritises over ``COVERAGE_RCFILE`` when both are present —
    this guard is the defense-in-depth layer that makes an active override visible and inert
    even if a future invocation path drops the explicit flag. Emitted ahead of the coverage
    gate's pytest invocation only (``PYTEST_ADDOPTS`` is unset by every pytest step; this one
    only ever mattered for ``do_coverage``).
    """
    return _warn_then_unset_guard("COVERAGE_RCFILE", "the coverage config is fixed at generation time")


def _lint_commands(facts: GateFacts) -> list[str]:
    target = _quoted(facts.lint_paths)
    return [f'"$PYTHON" -m ruff check {target}', f'"$PYTHON" -m ruff format --check {target}']


def _typecheck_commands(facts: GateFacts) -> list[str]:
    tool = '"$PYTHON" -m mypy' if facts.type_checker == "mypy" else "pyright"
    if _typecheck_env_form(facts):
        # Single path keeps the 1.0.x env-overridable form (a documented debug affordance).
        return [f'{tool} "$TYPECHECK_PATHS"']
    notice = _ignored_override_notice("TYPECHECK_PATHS")
    if facts.type_checker == "mypy":
        # One invocation per path is DELIBERATE for mypy: separate runs avoid
        # module-name collisions between roots (and the quoted env var can't hold a list).
        return [notice, *(f"{tool} {_quoted((path,))}" for path in facts.typecheck_paths)]
    # pyright has no such constraint and accepts many paths; one invocation avoids
    # paying its startup cost once per path.
    return [notice, f"{tool} {_quoted(facts.typecheck_paths)}"]


def _coverage_command(facts: GateFacts) -> list[str]:
    """The coverage step's shell lines: env-override guards, then the pytest-cov call.

    ``--cov=`` and ``--cov-fail-under=`` are ALWAYS generation-time literals now — a live
    ``COVERAGE_SOURCE``/``COV_FAIL_UNDER`` cannot widen the measured source or lower the
    threshold at runtime, single-source or multi-source alike. That closes the gap where
    ``COV_FAIL_UNDER=0`` (or a narrow ``COVERAGE_SOURCE``) made the gate trivially pass; see
    the ``harden-quality-gate-integrity`` change.

    ``--cov-config=pyproject.toml`` is ALSO a generation-time literal, for the sibling gap in
    the same change class: every project this generator serves already declares its real
    ``[tool.coverage.report]`` (``fail_under``, ``exclude_lines``) in its own ``pyproject.toml``
    at the directory the gate script runs from (every ``Makefile``/CI caller invokes this
    script with that directory as ``cwd`` — never a relative ``cd`` first), so pointing the
    flag there costs nothing new to detect and closes the ``COVERAGE_RCFILE`` evasion: an
    explicit ``--cov-config`` takes priority over that env var in coverage.py's own config
    resolution, so a rogue export pointed at a permissive rc file (``fail_under=0``, a broad
    ``exclude_lines``) can no longer widen what this gate measures. See
    ``docs/plans/eval-evidence-integrity/PLAN.md`` Phase 1.

    One ``--cov=`` flag per source, unconditionally. There used to be a dedicated
    single-source form that built the flag from ``_quoted(facts.coverage_source)`` directly;
    for exactly one source that is byte-identical to this general, repeat-the-flag form
    (joining one element is a no-op), so the dedicated form was dead weight, not a behavior
    difference. Collapsing to one path removes that now-pointless branch.
    """
    cov = " ".join(f"--cov={_quoted((src,))}" for src in facts.coverage_source)
    return [
        _ignored_override_notice("COVERAGE_SOURCE"),
        _ignored_override_notice("COV_FAIL_UNDER"),
        *_pytest_addopts_guard(),
        *_coverage_rcfile_guard(),
        f'"$PYTHON" -m pytest {cov} --cov-config=pyproject.toml --cov-branch --cov-report=term-missing --cov-fail-under={facts.cov_fail_under}',
    ]


def _step_commands(facts: GateFacts) -> dict[str, list[str]]:
    """Ordered ``{step: [shell command lines]}`` for the steps this project supports."""
    steps: dict[str, list[str]] = {}
    if facts.has_ruff:
        steps["lint"] = _lint_commands(facts)
    if facts.type_checker in ("mypy", "pyright"):
        steps["typecheck"] = _typecheck_commands(facts)
    if facts.has_pytest:
        steps["test"] = [*_pytest_addopts_guard(), '"$PYTHON" -m pytest']
    if facts.has_pytest_cov:
        steps["coverage"] = _coverage_command(facts)
    return steps


def _header(regen_args: tuple[str, ...], regen_program: str) -> list[str]:
    lines = [
        "#!/usr/bin/env bash",
        "# quality-gate.sh - generated by the quality-gate skill.",
        "# Single source of truth for this project's checks: run it locally and in CI so the",
        "# two never drift. Hand extensions live below the marker near the end of this file.",
    ]
    if regen_args:
        # Provenance: the exact invocation that reproduces the generated prefix, so anyone
        # can re-run it (and --check verifies against the same inputs). regen_program is the
        # generator path AS INVOKED (cwd-relative, exactly like --root/--out), so the whole
        # line replays from the same cwd. shlex.quote keeps it copy-paste reproducible for
        # paths with spaces/metachars, and is deterministic so byte-stability holds.
        joined = " ".join(shlex.quote(a) for a in (regen_program, *regen_args))
        # A control character inside a quoted arg would break out of this comment line into
        # executable script text (shlex.quote preserves real newlines). Such an invocation
        # cannot be represented on one comment line, so omit provenance rather than emit a
        # corrupted (and injectable) header.
        if "\n" not in joined and "\r" not in joined:
            lines.append("# regenerate: python " + joined)
    lines += [
        "#",
        "# Usage: ./scripts/quality-gate.sh [lint|typecheck|test|coverage|all]   (default: all)",
        "set -euo pipefail",
    ]
    return lines


def _variables(facts: GateFacts, steps: dict[str, list[str]]) -> list[str]:
    """Overridable ``${VAR:-default}`` declarations for the steps this project supports.

    ``COVERAGE_SOURCE``/``COV_FAIL_UNDER`` are deliberately NOT declared here (unlike
    ``TYPECHECK_PATHS``, whose single-path env-override stays a documented debug affordance
    for a non-thresholded check): both are gate-integrity values baked into the coverage
    command as generation-time literals by :func:`_coverage_command`, so a variable
    declaration here would just be dead, unreferenced shell.
    """
    out = [f'PYTHON="${{PYTHON:-{_sh_escape(facts.python)}}}"']
    if "typecheck" in steps and _typecheck_env_form(facts):
        out.append(f'TYPECHECK_PATHS="${{TYPECHECK_PATHS:-{_sh_escape(facts.typecheck_paths[0])}}}"')
    return out


def _func(name: str, body: list[str]) -> list[str]:
    return [f"do_{name}() {{", f'  log "{name}"', *[f"  {cmd}" for cmd in body], "}"]


def _do_all(steps: dict[str, list[str]]) -> list[str]:
    calls = [f"do_{n}" for n in ("lint", "typecheck") if n in steps]
    if "coverage" in steps:  # coverage runs the tests too — don't run them twice
        calls.append("do_coverage")
    elif "test" in steps:
        calls.append("do_test")
    return [
        "do_all() {",
        *[f"  {call}" for call in calls],
        "  # Hand-maintained extension hook (defined below the marker, when present).",
        "  if declare -F do_extra >/dev/null; then",
        "    do_extra",
        "  fi",
        '  log "PASS"',
        "}",
    ]


def _main(steps: dict[str, list[str]]) -> list[str]:
    present = [n for n in _ORDER if n in steps]
    arms = [f"    {n}) do_{n} ;;" for n in present]
    arms.append("    all) do_all ;;")
    usage = "|".join([*present, "all"])
    arms.append(f'    *) echo "usage: $0 [{usage}]" >&2; exit 2 ;;')
    return ["main() {", '  local cmd="${1:-all}"', '  case "$cmd" in', *arms, "  esac", "}"]


def render_gate(
    facts: GateFacts,
    regen_args: tuple[str, ...] = (),
    regen_program: str = "scripts/gen_gate.py",
) -> str:
    """Return the full quality-gate script text (ends with exactly one newline).

    ``regen_args`` is the canonical CLI invocation that produced this render; when given it
    is embedded as a provenance comment so the artifact documents its own regeneration.
    ``regen_program`` is the generator path exactly as invoked (cwd-relative, like the args
    themselves) — callers pass ``sys.argv[0]`` so the provenance line actually replays.
    """
    steps = _step_commands(facts)
    body: list[str] = [*_header(regen_args, regen_program), "", *_variables(facts, steps), "", _LOG, ""]
    for name in _ORDER:
        if name in steps:
            body.extend(_func(name, steps[name]))
            body.append("")
    body.extend(_do_all(steps))
    body.append("")
    body.extend(_main(steps))
    body.extend(["", MARKER, *_DEFAULT_TAIL])
    return "\n".join(body).rstrip("\n") + "\n"


def render_ci_snippet() -> str:
    """A minimal GitHub Actions step that runs the SAME script, keeping CI == local."""
    return (
        "# Add to your CI workflow so it runs the identical gate (local == CI):\n"
        "- name: Quality gate\n"
        "  run: ./scripts/quality-gate.sh all\n"
    )
