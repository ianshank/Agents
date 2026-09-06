#!/usr/bin/env python3
"""Advisory checker for ADR 0037 branch protection on ``main``.

Derives the candidate required-check set from
``.github/workflows/required-check-stubs.yml`` (never a restated name list).
Optionally probes GitHub via ``gh api``. Default exit 0: this cannot enable
protection (admin settings are out-of-band) and must not fail CI. ``--strict``
fails when protection is absent or a derived check is missing from the live
required-status-check list.

Usage::

    python scripts/check_branch_protection.py
    python scripts/check_branch_protection.py --probe
    python scripts/check_branch_protection.py --strict --probe
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:  # pragma: no cover - import bootstrap
    sys.path.insert(0, str(_HERE))

from _cli import configure_logging  # noqa: E402
from required_check_names import (  # noqa: E402
    DEFAULT_STUB_WORKFLOW,
    CheckNameError,
    candidate_required_contexts,
)

logger = logging.getLogger(__name__)

GitRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class BranchProtectionConfig:
    """Operator tunables. Empty env values are ignored at the CLI, not here."""

    stub_workflow: str = DEFAULT_STUB_WORKFLOW
    branch: str = "main"
    repository_env_var: str = "GITHUB_REPOSITORY"
    protection_api: str = "repos/{owner}/{repo}/branches/{branch}/protection"
    gh_command: str = "gh"
    timeout_s: float = 30.0


@dataclass(frozen=True)
class ProtectionReport:
    """Comparable snapshot. ``live_contexts`` is None when not probed."""

    branch: str
    expected: tuple[str, ...]
    live_contexts: tuple[str, ...] | None
    protected: bool | None
    missing: tuple[str, ...]
    extra: tuple[str, ...]
    probe_error: str | None

    @property
    def ok(self) -> bool:
        if self.probe_error:
            return False
        if self.protected is False:
            return False
        if self.live_contexts is None:
            return True  # derived-only run: nothing to disagree with
        return not self.missing


def parse_owner_repo(
    raw: str | None,
    cfg: BranchProtectionConfig | None = None,
    environ: Mapping[str, str] | None = None,
) -> tuple[str, str] | None:
    """``owner/repo`` from an argument, else ``GITHUB_REPOSITORY``. None if unset."""
    conf = cfg or BranchProtectionConfig()
    env = os.environ if environ is None else environ
    value = (raw or env.get(conf.repository_env_var, "")).strip()
    if not value or "/" not in value:
        return None
    owner, _, repo = value.partition("/")
    if not owner or not repo or "/" in repo:
        return None
    return owner, repo


def contexts_from_protection_payload(payload: Mapping[str, Any]) -> tuple[str, ...]:
    """Required-check context names from the GitHub branch-protection JSON."""
    checks = payload.get("required_status_checks") or {}
    if not isinstance(checks, Mapping):
        return ()
    names: set[str] = set()
    for ctx in checks.get("contexts") or ():
        names.add(str(ctx))
    for item in checks.get("checks") or ():
        if isinstance(item, Mapping) and item.get("context"):
            names.add(str(item["context"]))
    return tuple(sorted(names))


def _default_runner(cfg: BranchProtectionConfig) -> GitRunner:
    def run(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [cfg.gh_command, *args],
            capture_output=True,
            text=True,
            timeout=cfg.timeout_s,
            check=False,
        )

    return run


def probe_protection(
    owner: str,
    repo: str,
    cfg: BranchProtectionConfig | None = None,
    *,
    runner: GitRunner | None = None,
) -> tuple[bool | None, tuple[str, ...] | None, str | None]:
    """Return ``(protected, contexts, error)``. 404 means unprotected, not a crash."""
    conf = cfg or BranchProtectionConfig()
    run = runner or _default_runner(conf)
    api = conf.protection_api.format(owner=owner, repo=repo, branch=conf.branch)
    try:
        proc = run(["api", api])
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, None, str(exc)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        if "404" in err or "Branch not protected" in err or "Not Found" in err:
            return False, (), None
        return None, None, err or f"{conf.gh_command} api exited {proc.returncode}"
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return None, None, f"protection payload is not JSON: {exc}"
    if not isinstance(payload, dict):
        return None, None, "protection payload is not an object"
    return True, contexts_from_protection_payload(payload), None


def build_report(
    *,
    repo_root: Path,
    cfg: BranchProtectionConfig | None = None,
    owner_repo: str | None = None,
    probe: bool = False,
    environ: Mapping[str, str] | None = None,
    runner: GitRunner | None = None,
) -> ProtectionReport:
    conf = cfg or BranchProtectionConfig()
    expected = candidate_required_contexts(repo=repo_root, stub_workflow=conf.stub_workflow)
    live: tuple[str, ...] | None = None
    protected: bool | None = None
    probe_error: str | None = None
    if probe:
        parsed = parse_owner_repo(owner_repo, conf, environ)
        if parsed is None:
            probe_error = f"need owner/repo via --repository or ${conf.repository_env_var}"
        else:
            owner, name = parsed
            protected, live, probe_error = probe_protection(owner, name, conf, runner=runner)
    missing: tuple[str, ...] = ()
    extra: tuple[str, ...] = ()
    if live is not None:
        live_set = set(live)
        missing = tuple(c for c in expected if c not in live_set)
        extra = tuple(c for c in live if c not in set(expected))
    elif protected is False:
        missing = expected
    return ProtectionReport(
        branch=conf.branch,
        expected=expected,
        live_contexts=live,
        protected=protected,
        missing=missing,
        extra=extra,
        probe_error=probe_error,
    )


def _emit(report: ProtectionReport) -> None:
    print(f"branch={report.branch}")
    print(f"derived_required_checks={len(report.expected)}")
    for name in report.expected:
        print(f"  expected: {name}")
    if report.probe_error:
        print(f"probe_error={report.probe_error}")
        return
    if report.protected is None and report.live_contexts is None:
        print("probe=skipped (pass --probe to query GitHub)")
        return
    print(f"protected={report.protected}")
    if report.live_contexts is not None:
        print(f"live_required_checks={len(report.live_contexts)}")
    for name in report.missing:
        print(f"  missing: {name}")
    for name in report.extra:
        print(f"  extra: {name}")
    print(f"ok={report.ok}")


def main(argv: list[str] | None = None) -> int:
    cfg = BranchProtectionConfig()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", default=".", help="repository root (default: cwd)")
    ap.add_argument("--stub-workflow", default=cfg.stub_workflow)
    ap.add_argument("--branch", default=cfg.branch)
    ap.add_argument("--repository", help="owner/repo; default GITHUB_REPOSITORY")
    ap.add_argument("--probe", action="store_true", help="query GitHub via gh api")
    ap.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 when protection is absent or a derived check is missing",
    )
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)
    configure_logging(verbose=args.verbose)
    conf = BranchProtectionConfig(
        stub_workflow=args.stub_workflow,
        branch=args.branch,
    )
    try:
        report = build_report(
            repo_root=Path(args.repo_root).resolve(),
            cfg=conf,
            owner_repo=args.repository,
            probe=args.probe,
        )
    except (OSError, CheckNameError) as exc:
        logger.error("%s", exc)
        print(f"check-branch-protection error: {exc}", file=sys.stderr)
        return 2
    _emit(report)
    if args.strict and not report.ok:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
