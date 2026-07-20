"""Command-line interface for the backend-validation experiment.

Exit codes extend the repo's script contract (``scripts/check_size_budget.py`` docstring
pattern): 0 OK, 1 FAIL, 2 usage/config error, 3 BLOCKED (precondition; a blocked_report.md
was written), 4 HALT (unexpected negative-control pass). Every command ends with one
verdict line: ``backend-validation[<phase>]: STATUS — reason``.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from backend_validation.deploy import DeployError, pin_compose_file
from backend_validation.deploy_phase import run_deploy, run_down
from backend_validation.isolation import IsolationError, check_isolation
from backend_validation.l2_phase import run_l2
from backend_validation.logging_util import configure_logging, get_logger
from backend_validation.phases import PhaseResult, default_phase_io, run_l1, run_preflight
from backend_validation.procrun import SubprocessRunner
from backend_validation.report_phase import run_all, run_report
from backend_validation.settings import Settings, SettingsError, load_settings

logger = get_logger(__name__)

SUBTREE_ROOT = Path(__file__).resolve().parents[1]
SUBTREE_REL = "experiments/backend-validation/"
EXIT_USAGE_ERROR = 2

# PR-scoped zero-writes allowlist: the subtree itself plus the root files this experiment's
# PR is allowed to touch (docs + the optional Makefile delegation target). Extendable per
# invocation with --allow; deliberately NOT part of the permanent quality gate (post-merge
# it would flag unrelated branches' files).
DEFAULT_ALLOWLIST = (
    SUBTREE_REL,
    "Makefile",
    "CHANGELOG.md",
    "NEXT_STEPS.md",
    "README.md",
)


def _default_run_id() -> str:
    return datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%SZ")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_parser() -> argparse.ArgumentParser:
    # Common flags live on a parent parser attached to every subcommand, so
    # `backend-validation preflight --config X` parses (flags AFTER the subcommand —
    # the way the Makefile and gate tail invoke it).
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-v", "--verbose", action="store_true", help="Enable DEBUG logging")
    common.add_argument("--config", type=Path, default=SUBTREE_ROOT / "config.yaml", help="Settings file")
    common.add_argument(
        "--override", action="append", default=[], metavar="KEY.PATH=VALUE", help="Dotted settings override"
    )

    parser = argparse.ArgumentParser(
        prog="backend-validation",
        description="eval-backend-validation_v1 phase runner (probes emit observables; the signed rubric marks)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    preflight = sub.add_parser(
        "preflight", parents=[common], help="P0: validate TCB artifacts + environment; STOP until signed"
    )
    preflight.add_argument(
        "--schema-only",
        action="store_true",
        help="Structural validation only (quality-gate mode; ignores sign-off and environment)",
    )

    deploy = sub.add_parser("deploy", parents=[common], help="P1: stand up stacks; record ops-burden metrics")
    deploy.add_argument("--backend", help="Deploy a single configured backend")
    deploy.add_argument("--run-id", default=None, help="Evidence directory name (default: UTC timestamp)")

    down = sub.add_parser("down", parents=[common], help="Tear down experiment stacks")
    down.add_argument("--backend", help="Tear down a single configured backend")

    sub.add_parser("pin-digests", parents=[common], help="Resolve compose image tags to sha256 digests")

    l1 = sub.add_parser("l1", parents=[common], help="P2: L1 capability probes + negative controls")
    l1.add_argument("--backend", help="Probe a single configured backend")
    l1.add_argument("--run-id", default=None, help="Evidence directory name (default: UTC timestamp)")

    l2 = sub.add_parser("l2", parents=[common], help="P3: integration probes through the harness sink seam")
    l2.add_argument("--run-id", default=None, help="Evidence directory name (default: UTC timestamp)")

    report = sub.add_parser("report", parents=[common], help="P5: render claimed-vs-observed from recorded evidence")
    report.add_argument("--run-id", required=True, help="The run whose observables to render")

    all_cmd = sub.add_parser("all", parents=[common], help="Chain P0->P2->P3->P5 (stops on BLOCKED/HALT)")
    all_cmd.add_argument("--run-id", default=None, help="Evidence directory name (default: UTC timestamp)")

    isolation = sub.add_parser("isolation", parents=[common], help="PR-scoped zero-writes check against a base ref")
    isolation.add_argument("--base-ref", default="origin/main", help="Base ref to diff against")
    isolation.add_argument(
        "--allow", action="append", default=[], metavar="PATH", help="Extra allowlist entry (prefix if it ends in /)"
    )
    return parser


def _verdict(result: PhaseResult) -> int:
    print(f"backend-validation[{result.phase}]: {result.status} — {result.reason}")
    for artifact in result.artifacts:
        print(f"  evidence: {artifact}")
    return result.exit_code


def _load_settings_or_none(args: argparse.Namespace) -> Settings | None:
    try:
        return load_settings(args.config, overrides=args.override)
    except SettingsError as exc:
        print(f"backend-validation[{args.command}]: FAIL — invalid configuration: {exc}")
        return None


def _cmd_preflight(args: argparse.Namespace) -> int:
    settings = _load_settings_or_none(args)
    if settings is None:
        return EXIT_USAGE_ERROR
    result = run_preflight(SUBTREE_ROOT, settings, default_phase_io(), schema_only=args.schema_only)
    return _verdict(result)


def _cmd_l1(args: argparse.Namespace) -> int:
    settings = _load_settings_or_none(args)
    if settings is None:
        return EXIT_USAGE_ERROR
    run_id = args.run_id or _default_run_id()
    result = run_l1(SUBTREE_ROOT, settings, default_phase_io(), run_id=run_id, only_backend=args.backend)
    return _verdict(result)


def _cmd_deploy(args: argparse.Namespace) -> int:
    settings = _load_settings_or_none(args)
    if settings is None:
        return EXIT_USAGE_ERROR
    run_id = args.run_id or _default_run_id()
    result = run_deploy(
        SUBTREE_ROOT,
        settings,
        env=dict(os.environ),
        run_id=run_id,
        only_backend=args.backend,
        now_fn=_utc_now,
    )
    return _verdict(result)


def _cmd_down(args: argparse.Namespace) -> int:
    settings = _load_settings_or_none(args)
    if settings is None:
        return EXIT_USAGE_ERROR
    return _verdict(run_down(SUBTREE_ROOT, settings, only_backend=args.backend))


def _cmd_pin_digests(args: argparse.Namespace) -> int:
    settings = _load_settings_or_none(args)
    if settings is None:
        return EXIT_USAGE_ERROR
    runner = SubprocessRunner()
    compose_paths = [SUBTREE_ROOT / spec.compose_file for spec in settings.backends]
    compose_paths.append(SUBTREE_ROOT / "deploy" / "judge" / "compose.yaml")
    total = 0
    for compose_path in compose_paths:
        try:
            pinned = pin_compose_file(compose_path, runner)
        except DeployError as exc:
            print(f"backend-validation[pin-digests]: FAIL — {exc}")
            return 1
        for base, digest in pinned:
            print(f"  pinned {base} -> {digest}")
        total += len(pinned)
    print(f"backend-validation[pin-digests]: OK — pinned {total} image(s); update deploy/DIGESTS.md and commit")
    return 0


def _cmd_l2(args: argparse.Namespace) -> int:
    settings = _load_settings_or_none(args)
    if settings is None:
        return EXIT_USAGE_ERROR
    run_id = args.run_id or _default_run_id()
    return _verdict(run_l2(SUBTREE_ROOT, settings, run_id=run_id, now_fn=_utc_now))


def _cmd_report(args: argparse.Namespace) -> int:
    settings = _load_settings_or_none(args)
    if settings is None:
        return EXIT_USAGE_ERROR
    return _verdict(run_report(SUBTREE_ROOT, settings, run_id=args.run_id, now_fn=_utc_now))


def _cmd_all(args: argparse.Namespace) -> int:
    settings = _load_settings_or_none(args)
    if settings is None:
        return EXIT_USAGE_ERROR
    run_id = args.run_id or _default_run_id()
    results = run_all(SUBTREE_ROOT, settings, run_id=run_id, now_fn=_utc_now, l2_runner=run_l2)
    exit_code = 0
    for result in results:
        exit_code = _verdict(result) or exit_code
    return exit_code


def _cmd_isolation(args: argparse.Namespace) -> int:
    runner = SubprocessRunner()
    toplevel = runner.run(["git", "rev-parse", "--show-toplevel"], cwd=SUBTREE_ROOT)
    if not toplevel.ok:
        print(f"backend-validation[isolation]: FAIL — not inside a git repository: {toplevel.stderr.strip()}")
        return EXIT_USAGE_ERROR
    repo_root = Path(toplevel.stdout.strip())
    allowlist = (*DEFAULT_ALLOWLIST, *args.allow)
    try:
        result = check_isolation(repo_root=repo_root, base_ref=args.base_ref, allowlist=allowlist, runner=runner)
    except IsolationError as exc:
        print(f"backend-validation[isolation]: FAIL — {exc}")
        return EXIT_USAGE_ERROR
    if result.ok:
        print(f"backend-validation[isolation]: OK — {result.checked_paths} changed path(s), all inside the allowlist")
        return 0
    print(f"backend-validation[isolation]: FAIL — {len(result.violations)} path(s) escape the subtree allowlist:")
    for violation in result.violations:
        print(f"  {violation}")
    return 1


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.verbose)
    handlers = {
        "preflight": _cmd_preflight,
        "deploy": _cmd_deploy,
        "down": _cmd_down,
        "pin-digests": _cmd_pin_digests,
        "l1": _cmd_l1,
        "l2": _cmd_l2,
        "report": _cmd_report,
        "all": _cmd_all,
        "isolation": _cmd_isolation,
    }
    return handlers[args.command](args)


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess in the live suite
    sys.exit(main())
