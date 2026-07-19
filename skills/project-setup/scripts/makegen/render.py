"""Render :class:`ProjectFacts` into a deterministic, POSIX/GNU Makefile.

The output is byte-stable (no timestamps, stable target order) so re-running the generator
on an unchanged project yields an identical file. Recipe lines are indented with a hard TAB
(``\\t``) — Make rejects space-indented recipes, so this is enforced by a test.

Composition: when the project already has ``scripts/quality-gate.sh`` the lint/typecheck/
test/coverage/check targets *delegate* to it (single source of truth); otherwise they emit
the tool commands inline so the Makefile is useful on its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .model import ProjectFacts
from .workspace import WorkspaceFacts

_TAB = "\t"

# Self-documenting `make help`: print every `target: ## text` line, aligned. `$$` escapes
# Make's own expansion so awk receives `$1`/`$2`; `\033[36m` colours the target name.
_HELP_RECIPE = (
    '@awk \'BEGIN {FS = ":.*## "} '
    "/^[a-zA-Z0-9_-]+:.*## / "
    '{printf "  \\033[36m%-14s\\033[0m %s\\n", $$1, $$2}\' $(MAKEFILE_LIST)'
)

_CLEAN_RECIPE = (
    "rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov build dist",
    "find . -type d -name '__pycache__' -prune -exec rm -rf {} +",
    "find . -type d -name '*.egg-info' -prune -exec rm -rf {} +",
)


@dataclass(frozen=True)
class _Target:
    name: str
    help: str
    recipe: tuple[str, ...] = ()
    prereqs: tuple[str, ...] = field(default_factory=tuple)


def _lint_target(facts: ProjectFacts, delegate: bool) -> _Target | None:
    # Never fabricate: no ruff -> no lint target, even when delegating (the gate script
    # would omit the step and `quality-gate.sh lint` would error).
    if not facts.has_ruff:
        return None
    if delegate:
        return _Target("lint", "Lint (via the quality-gate script)", ("./scripts/quality-gate.sh lint",))
    return _Target("lint", "Lint the code", ("$(PYTHON) -m ruff check .",))


def _typecheck_target(facts: ProjectFacts, delegate: bool) -> _Target | None:
    if not facts.type_checker:
        return None
    if delegate:
        return _Target(
            "typecheck", "Type-check (via the quality-gate script)", ("./scripts/quality-gate.sh typecheck",)
        )
    if facts.type_checker == "mypy":
        return _Target("typecheck", "Type-check the code", ("$(PYTHON) -m mypy $(TYPECHECK_PATHS)",))
    return _Target("typecheck", "Type-check the code", (f"{facts.type_checker} $(TYPECHECK_PATHS)",))


def _test_target(facts: ProjectFacts, delegate: bool) -> _Target | None:
    if not facts.has_pytest:
        return None
    if delegate:
        return _Target("test", "Run tests (via the quality-gate script)", ("./scripts/quality-gate.sh test",))
    return _Target("test", "Run the test suite", ("$(PYTHON) -m pytest",))


def _coverage_target(facts: ProjectFacts, delegate: bool) -> _Target | None:
    if not facts.has_pytest_cov:
        return None
    if delegate:
        return _Target(
            "coverage", "Run tests with coverage (via the quality-gate script)", ("./scripts/quality-gate.sh coverage",)
        )
    cmd = "$(PYTHON) -m pytest --cov=$(COVERAGE_SOURCE) --cov-branch --cov-report=term-missing --cov-fail-under=$(COV_FAIL_UNDER)"
    return _Target("coverage", "Run tests with a coverage threshold", (cmd,))


def _check_target(facts: ProjectFacts, targets: list[_Target]) -> _Target | None:
    if facts.has_quality_gate_script:
        return _Target("check", "Run the full quality gate", ("./scripts/quality-gate.sh all",))
    names = {t.name for t in targets}
    prereqs = tuple(n for n in ("lint", "typecheck", "test") if n in names)
    if not prereqs:
        return None
    return _Target("check", "Run all quality checks", (), prereqs)


def _build_targets(facts: ProjectFacts) -> list[_Target]:
    delegate = facts.has_quality_gate_script
    targets: list[_Target] = [
        _Target("help", "Show this help", (_HELP_RECIPE,)),
        _Target("install", "Install the project and its dependencies", (facts.install_cmd,)),
    ]
    if facts.has_ruff:
        targets.append(_Target("format", "Auto-format the code", ("$(PYTHON) -m ruff format .",)))
    optional = (
        _lint_target(facts, delegate),
        _typecheck_target(facts, delegate),
        _test_target(facts, delegate),
        _coverage_target(facts, delegate),
    )
    targets.extend(t for t in optional if t is not None)
    check = _check_target(facts, targets)
    if check is not None:
        targets.append(check)
    if facts.has_build_backend:
        targets.append(_Target("build", "Build distributables", ("$(PYTHON) -m build",)))
    targets.append(_Target("clean", "Remove caches and build artifacts", _CLEAN_RECIPE))
    if facts.has_deploy_script:
        targets.append(_Target("deploy", "Deploy (delegates to the deploy script)", ("./scripts/deploy.sh release",)))
    return targets


def _variables(facts: ProjectFacts, workspace: WorkspaceFacts | None = None) -> list[str]:
    delegate = facts.has_quality_gate_script
    out = [f"PYTHON ?= {facts.python}"]
    # install-all uses $(PIP) even when the root's own install command does not.
    if "$(PIP)" in facts.install_cmd or (workspace is not None and workspace.is_workspace):
        out.append("PIP ?= $(PYTHON) -m pip")
    if not delegate and facts.type_checker in ("mypy", "pyright"):
        out.append(f"TYPECHECK_PATHS ?= {facts.typecheck_paths}")
    if not delegate and facts.has_pytest_cov:
        out.append(f"COVERAGE_SOURCE ?= {facts.coverage_source}")
        out.append(f"COV_FAIL_UNDER ?= {facts.cov_fail_under}")
    return out


def supports_check(facts: ProjectFacts) -> bool:
    """True when ``render_makefile(facts)`` will emit a ``check`` target.

    The workspace fan-out uses this to avoid fabricating ``$(MAKE) -C <member> check``
    delegations into member Makefiles that have nothing gate-able (make would fail with
    "No rule to make target 'check'").
    """
    return any(t.name == "check" for t in _build_targets(facts))


def _workspace_targets(
    workspace: WorkspaceFacts, base_names: set[str], checkable: tuple[str, ...] | None
) -> list[_Target]:
    """Fan-out targets for a monorepo root.

    ``$(MAKE) -C <member>`` (not root-cwd loops) is deliberate: cwd-correctness for ruff
    config discovery, mypy_path, pytest testpaths and coverage config falls out for free,
    mirroring CI's per-package ``working-directory``. ``checkable`` restricts the check
    fan-out to members whose own Makefile has a ``check`` target (None = all — callers who
    have not detected member facts); install/clean aggregates always cover every member,
    because those targets are unconditionally emitted in member Makefiles.
    """
    check_members = workspace.members if checkable is None else tuple(m for m in workspace.members if m in checkable)
    targets: list[_Target] = []
    for member in check_members:
        targets.append(_Target(f"check-{member}", f"Run {member}'s quality checks", (f"$(MAKE) -C {member} check",)))
    # Root's own `check` joins the aggregate only when the root actually has one
    # (never fabricate a prerequisite on a target that does not exist).
    aggregate: list[str] = ["check"] if "check" in base_names else []
    aggregate += [f"check-{m}" for m in check_members]
    targets.append(_Target("check-all", "Run root and every member's quality checks", (), tuple(aggregate)))
    install_cmd = "$(PIP) install " + " ".join(f"-e ./{m}" for m in workspace.members)
    targets.append(_Target("install-all", "Editable-install every workspace member", (install_cmd,)))
    targets.append(
        _Target(
            "clean-all",
            "Clean the root and every member",
            tuple(f"$(MAKE) -C {m} clean" for m in workspace.members),
            ("clean",),
        )
    )
    return targets


def _render_target(target: _Target) -> list[str]:
    header = target.name + ":"
    if target.prereqs:
        header += " " + " ".join(target.prereqs)
    header += f" ## {target.help}"
    return [header] + [_TAB + line for line in target.recipe]


def render_makefile(
    facts: ProjectFacts,
    workspace: WorkspaceFacts | None = None,
    checkable_members: tuple[str, ...] | None = None,
) -> str:
    """Return the full Makefile text for ``facts`` (ends with exactly one newline).

    ``workspace`` (optional, additive — single-package callers are unchanged) appends a
    fan-out section: one explicit ``check-<member>`` per check-capable member plus
    ``check-all`` / ``install-all`` / ``clean-all`` aggregates. ``checkable_members``
    (None = assume all) names the members whose own Makefile carries a ``check`` target —
    see :func:`supports_check`. Explicit targets over pattern rules for greppability and
    byte-stability. Env vars (e.g. HYPOTHESIS_PROFILE) propagate through ``$(MAKE) -C``
    and recipes with no generator involvement.
    """
    targets = _build_targets(facts)
    ws_targets: list[_Target] = []
    if workspace is not None and workspace.is_workspace:
        ws_targets = _workspace_targets(workspace, {t.name for t in targets}, checkable_members)
    lines = [
        "# Makefile - generated by the project-setup skill.",
        "# Deterministic scaffold: safe to extend by hand. Targets POSIX/GNU make",
        "# (Linux, macOS, WSL). Run `make help` for the available targets.",
        "",
        ".DEFAULT_GOAL := help",
        ".DELETE_ON_ERROR:",
        "",
        *_variables(facts, workspace),
        "",
        ".PHONY: " + " ".join(t.name for t in [*targets, *ws_targets]),
        "",
    ]
    for target in targets:
        lines.extend(_render_target(target))
        lines.append("")
    if ws_targets:
        lines.append("# --- workspace (monorepo) fan-out: one target per member package ---")
        lines.append("")
        for target in ws_targets:
            lines.extend(_render_target(target))
            lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"
