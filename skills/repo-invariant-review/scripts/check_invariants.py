#!/usr/bin/env python3
"""Check a change (or a proposal describing one) against this repo's enforced invariants.

Generic peer review asks whether a plan is *good*. This asks a narrower, mechanical
question: **would this change collide with a rule the repo already enforces in CI?**
Every check below corresponds to a gate that exists, so a finding here predicts a
concrete CI failure rather than expressing an opinion.

The checks, and the gate each one predicts:

======================  ====================================================
check                   predicts a failure in
======================  ====================================================
protected_paths         ``.github`` protected-path guard (needs a label)
size_budget             ``scripts/check_size_budget.py`` (500-line hard fail)
airgap                  ``architecture-drift-guard`` (F-011/F-012)
surface_baselines       ``tests/test_public_surface.py`` (F-039, exact match)
registry_baselines      ``tests/test_plugin_registry_surface.py`` (F-039)
core_model_change       ``docs/CHARTER.md`` §4 invariant 1 (needs an ADR)
readme_registry_drift   ``docs.yml`` README/registry drift job
======================  ====================================================

Exit codes:
    0 - no collisions (or only advisory ones, without ``--strict``)
    1 - at least one blocking collision
    2 - usage error
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger("repo-invariant-review")


def _configure_logging(verbose: bool = False) -> None:
    """Configure root logging for CLI.

    Deliberately a local copy, not an import from scripts/_cli.py or skills/common —
    this skill is self-contained/vendorable by design (ADR 0009). Kept identical to its
    4 sibling copies (skills/quality-gate/scripts/gen_gate.py,
    skills/deploy/scripts/gen_deploy.py, skills/project-setup/scripts/gen_makefile.py,
    and this skill's own build_fixture.py; ADR 0034) so the duplication doesn't
    silently drift into 5 different behaviors. Previously defaulted to INFO with a
    differently-padded format string; this module has no logger.info(...) calls (only
    debug/warning), so standardizing to WARNING is a no-op for actual output here.
    """
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


#: Hard ceiling enforced by ``scripts/check_size_budget.py``. Single-sourced from that
#: script when it is importable, so this skill cannot drift from the real gate.
DEFAULT_MAX_FILE_LINES = 500

#: Paths whose change requires the ``eval-change-approved`` label. Read from
#: ``scripts/eval_protected_paths.py`` when available; this is the documented fallback
#: for running the skill outside the repo.
FALLBACK_PROTECTED = (
    "features.yaml",
    "features.schema.json",
    "scripts/validations/",
    "config/",
    "src/eval_harness/gating/",
    "src/eval_harness/scorers/",
    "src/eval_harness/judges/",
    "tests/",
    ".github/",
    "architecture.yaml",
)

#: Modules whose modification engages CHARTER §4 invariant 1 ("core models and the engine
#: stay unmodified"), which requires an ADR before the change lands.
CORE_MODEL_PATHS = ("src/eval_harness/core/types.py", "src/eval_harness/engine.py")

#: The structural airgap: neither side may import the other (F-011, negative test F-012).
AIRGAP_PAIRS = (("eval_harness", "flow_corpus"), ("flow_corpus", "eval_harness"))


@dataclass
class Finding:
    """One predicted CI collision."""

    check: str
    detail: str
    remedy: str
    blocking: bool = True


@dataclass
class Report:
    changed_files: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    @property
    def blocking(self) -> list[Finding]:
        return [f for f in self.findings if f.blocking]

    def to_dict(self) -> dict:
        # Sorted so the report is byte-stable for a given input — it is diffable and
        # safe to commit as a fixture.
        return {
            "changed_files": sorted(self.changed_files),
            "passed": not self.blocking,
            "findings": sorted(
                (asdict(f) for f in self.findings),
                key=lambda f: (f["check"], f["detail"]),
            ),
        }


def _run_git(args: list[str], repo: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        logger.debug("git %s failed: %s", " ".join(args), result.stderr.strip())
        return ""
    return result.stdout


def changed_files(repo: Path, base: str) -> list[str]:
    """Files differing from *base*, or the working-tree diff when base is unavailable."""
    out = _run_git(["diff", "--name-only", f"{base}...HEAD"], repo)
    if not out.strip():
        out = _run_git(["status", "--porcelain"], repo)
        return sorted({line[3:].strip() for line in out.splitlines() if line.strip()})
    return sorted({line.strip() for line in out.splitlines() if line.strip()})


def _protected_patterns(repo: Path) -> tuple[str, ...]:
    """Prefer the repo's own single source of truth over this skill's fallback copy."""
    source = repo / "scripts" / "eval_protected_paths.py"
    if not source.is_file():
        logger.debug("eval_protected_paths.py not found; using the fallback list")
        return FALLBACK_PROTECTED
    text = source.read_text(encoding="utf-8")
    found = re.findall(r'"([^"]+)"', text.split("PROTECTED_PATTERNS")[-1].split(")")[0])
    return tuple(found) or FALLBACK_PROTECTED


def _max_file_lines(repo: Path) -> int:
    source = repo / "scripts" / "check_size_budget.py"
    if source.is_file():
        match = re.search(r"^MAX_FILE_LINES\s*=\s*(\d+)", source.read_text(encoding="utf-8"), re.M)
        if match:
            return int(match.group(1))
    return DEFAULT_MAX_FILE_LINES


def _real_matcher(repo: Path) -> Callable[[str], bool] | None:
    """Load the repo's own ``is_protected`` so this skill matches exactly what CI matches.

    Importing beats re-implementing for the reason ``check_guard_reachability.py`` gives
    about the pattern list itself: a second copy recreates the divergence the guard exists
    to prevent. Returns ``None`` when the module is absent (running outside the repo),
    unloadable, or predates ``is_protected`` — in which case the caller falls back to
    :func:`_matches_protected` over :func:`_protected_patterns`, i.e. the patterns scraped
    from the guard when it is readable and ``FALLBACK_PROTECTED`` only when it is not.
    """
    source = repo / "scripts" / "eval_protected_paths.py"
    if not source.is_file():
        logger.debug("eval_protected_paths.py not found; falling back to prefix matching")
        return None
    # Executing the guard must not mutate the tree being reviewed: bytecode written into
    # <repo>/scripts/__pycache__/ shows up in `git status`, lands in `changed_files`, and
    # breaks this skill's byte-stability contract on the second run.
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location("_rir_eval_protected_paths", source)
        if spec is None or spec.loader is None:
            logger.debug("could not build an import spec for %s", source)
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        matcher = getattr(module, "is_protected", None)
    except Exception as exc:
        logger.warning("failed to load the repo's is_protected (%s); falling back to prefix matching", exc)
        return None
    finally:
        sys.dont_write_bytecode = previous
    if not callable(matcher):
        logger.debug("eval_protected_paths.py exposes no callable is_protected")
        return None

    def _match(path: str) -> bool:
        # Coerce: the loaded module is untyped, and a guard returning a truthy non-bool
        # must not leak `Any` into the caller's protected/unprotected decision.
        return bool(matcher(path))

    return _match


def _matches_protected(path: str, pattern: str) -> bool:
    """Fallback matcher, used only when the repo's own ``is_protected`` is unavailable.

    Patterns are globs (``tests/**``) or bare paths (``features.yaml``); metacharacters
    and trailing separators are stripped to a directory prefix. This is **not** equivalent
    to the real guard and must not be used when the real one can be loaded: a mid-path
    wildcard such as ``skills/*/tests/**`` strips to ``/tests`` and then matches nothing,
    so the skill would silently stop predicting a gate that still fires. That is the
    false-negative direction, which is why `_real_matcher` is preferred.
    """
    prefix = pattern.replace("**", "").replace("*", "").rstrip("/")
    if not prefix:
        return False
    return path == prefix or path.startswith(prefix + "/")


def check_protected_paths(repo: Path, files: list[str], has_label: bool) -> list[Finding]:
    matcher = _real_matcher(repo)
    if matcher is not None:
        hits = sorted({f for f in files if matcher(f)})
    else:
        patterns = _protected_patterns(repo)
        hits = sorted({f for f in files for p in patterns if _matches_protected(f, p)})
    if not hits or has_label:
        return []
    return [
        Finding(
            check="protected_paths",
            detail=f"{len(hits)} protected file(s) changed: {', '.join(hits[:5])}"
            + (f" (+{len(hits) - 5} more)" if len(hits) > 5 else ""),
            remedy="request the 'eval-change-approved' label and CODEOWNERS review, or split the PR by protection level",
        )
    ]


def check_size_budget(repo: Path, files: list[str]) -> list[Finding]:
    ceiling = _max_file_lines(repo)
    findings = []
    for name in files:
        path = repo / name
        if not path.is_file() or path.suffix != ".py":
            continue
        lines = len(path.read_text(encoding="utf-8", errors="replace").splitlines())
        if lines > ceiling:
            findings.append(
                Finding(
                    check="size_budget",
                    detail=f"{name} is {lines} lines (ceiling {ceiling})",
                    remedy="split into a submodule imported for its registration side effects",
                )
            )
        elif lines > ceiling * 0.9:
            findings.append(
                Finding(
                    check="size_budget",
                    detail=f"{name} is {lines} lines, within 10% of the {ceiling} ceiling",
                    remedy="plan the split now; the next feature in this file will breach it",
                    blocking=False,
                )
            )
    return findings


def check_airgap(repo: Path, files: list[str]) -> list[Finding]:
    findings = []
    for name in files:
        path = repo / name
        if not path.is_file() or path.suffix != ".py":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for owner, forbidden in AIRGAP_PAIRS:
            if f"/{owner}/" not in f"/{name}" and not name.startswith(("src/eval_harness", owner)):
                continue
            if re.search(rf"^\s*(from|import)\s+{forbidden}\b", text, re.M):
                findings.append(
                    Finding(
                        check="airgap",
                        detail=f"{name} imports {forbidden}, crossing the {owner} airgap",
                        remedy=f"route shared code through agent_core; do NOT add an {owner}->{forbidden} edge to architecture.yaml",
                    )
                )
    return findings


def check_core_model_change(repo: Path, files: list[str]) -> list[Finding]:
    touched = [f for f in files if f in CORE_MODEL_PATHS]
    if not touched:
        return []
    adr_added = any(f.startswith("docs/decisions/") for f in files)
    if adr_added:
        return []
    return [
        Finding(
            check="core_model_change",
            detail=f"core model/engine changed ({', '.join(touched)}) with no ADR in this change",
            remedy="CHARTER §4 invariant 1 forbids this; add a numbered ADR + a §3 Ratified Amendment, per CHARTER §6",
        )
    ]


def check_baselines(repo: Path, files: list[str]) -> list[Finding]:
    findings = []
    src_touched = any(f.startswith("src/") for f in files)
    for baseline, trigger, gate in (
        ("tests/public_surface_baseline.json", "an exported name", "tests/test_public_surface.py"),
        ("tests/plugin_registry_baseline.json", "a registered component", "tests/test_plugin_registry_surface.py"),
    ):
        if src_touched and baseline not in files:
            findings.append(
                Finding(
                    check="surface_baselines" if "public" in baseline else "registry_baselines",
                    detail=f"src/ changed but {baseline} was not regenerated",
                    remedy=f"if this change adds {trigger}, run `python {gate} --update` (a protected path)",
                    blocking=False,
                )
            )
    return findings


def check_readme_registry_drift(repo: Path, files: list[str]) -> list[Finding]:
    """Every registered component name must appear verbatim in both READMEs."""
    scorers_dir = repo / "src" / "eval_harness" / "scorers"
    if not scorers_dir.is_dir() or not any(f.startswith("src/eval_harness/scorers") for f in files):
        return []
    registered: set[str] = set()
    for path in scorers_dir.rglob("*.py"):
        registered |= set(re.findall(r'@SCORERS\.register\(\s*"([^"]+)"', path.read_text(encoding="utf-8")))
    findings = []
    for readme in ("README.md", "src/eval_harness/README.md"):
        doc = repo / readme
        if not doc.is_file():
            continue
        text = doc.read_text(encoding="utf-8")
        missing = sorted(n for n in registered if not re.search(rf"\b{re.escape(n)}\b", text))
        if missing:
            findings.append(
                Finding(
                    check="readme_registry_drift",
                    detail=f"{readme} omits registered scorer(s): {missing}",
                    remedy="list each name verbatim; brace-expansion shorthand does not satisfy the guard",
                )
            )
    return findings


def review(repo: Path, base: str, has_label: bool) -> Report:
    files = changed_files(repo, base)
    logger.debug("reviewing %d changed file(s) against %s", len(files), base)
    report = Report(changed_files=files)
    report.findings.extend(check_protected_paths(repo, files, has_label))
    report.findings.extend(check_size_budget(repo, files))
    report.findings.extend(check_airgap(repo, files))
    report.findings.extend(check_core_model_change(repo, files))
    report.findings.extend(check_baselines(repo, files))
    report.findings.extend(check_readme_registry_drift(repo, files))
    return report


def render_text(report: Report) -> str:
    if not report.findings:
        return f"repo-invariant-review: OK — {len(report.changed_files)} file(s), no predicted CI collisions."
    lines = ["repo-invariant-review: findings"]
    for finding in sorted(report.findings, key=lambda f: (not f.blocking, f.check)):
        marker = "BLOCKING" if finding.blocking else "advisory"
        lines.append(f"  [{marker}] {finding.check}: {finding.detail}")
        lines.append(f"      -> {finding.remedy}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", default=".", help="repository root (default: cwd)")
    parser.add_argument("--base", default="origin/main", help="base ref to diff against")
    parser.add_argument("--out", help="write the report here (default: stdout)")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument(
        "--has-label",
        action="store_true",
        help="the PR already carries 'eval-change-approved'; suppresses the protected-path finding",
    )
    parser.add_argument("--strict", action="store_true", help="advisory findings also fail the run")
    parser.add_argument("--verbose", action="store_true", help="debug logging")
    args = parser.parse_args(argv)
    _configure_logging(verbose=args.verbose)

    repo = Path(args.repo).resolve()
    if not (repo / ".git").exists():
        print(f"repo-invariant-review: {repo} is not a git repository", file=sys.stderr)
        return 2

    report = review(repo, args.base, args.has_label)
    rendered = json.dumps(report.to_dict(), indent=2, sort_keys=True) if args.format == "json" else render_text(report)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)

    failing = report.findings if args.strict else report.blocking
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main())
