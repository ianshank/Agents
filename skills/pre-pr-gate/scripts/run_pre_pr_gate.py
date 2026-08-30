#!/usr/bin/env python3
"""Run the repo's full pre-PR validation gate and report the result.

Thin wrapper around ``make <target>`` (default: ``pre-pr``), run in *root*. The
actual check battery lives in the Makefile -- the single source of truth a human
can also run by hand (``make pre-pr``) -- and is deliberately not duplicated here.
This script exists so the checklist is discoverable/invocable as a skill and its
own pass/fail is a script-checkable artifact (an optional JSON report), rather
than terminal output someone has to read and interpret by hand.

  python scripts/run_pre_pr_gate.py                                 # make pre-pr in .
  python scripts/run_pre_pr_gate.py --root ../.. --out report.json
  python scripts/run_pre_pr_gate.py --base-ref origin/develop
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_TARGET = "pre-pr"
DEFAULT_TIMEOUT_SECONDS = 1800


def _as_text(value: bytes | str | None) -> str:
    """Normalize a subprocess stream to ``str``.

    ``text=True`` makes a completed run's streams ``str`` at runtime, but
    ``subprocess.TimeoutExpired.stdout``/``.stderr`` are typed generically as
    ``bytes | str | None`` regardless of the call site's own ``text=`` argument, so
    this stays honest for both rather than assuming the runtime-only guarantee.
    """
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def run_gate(root: Path, target: str, base_ref: str | None, timeout: int) -> tuple[bool, int, str]:
    """Invoke ``make <target>`` in *root*; return ``(passed, exit_code, combined_output)``.

    ``base_ref`` (when given) is passed through as a ``make`` variable override
    (``PRE_PR_BASE_REF=...``) rather than baked into the command line, so the same
    wrapper works against any fixture/target Makefile that exposes that variable --
    or is silently ignored by one that doesn't.
    """
    cmd = ["make", target]
    if base_ref is not None:
        cmd.append(f"PRE_PR_BASE_REF={base_ref}")
    logger.info("running: %s (cwd=%s, timeout=%ss)", " ".join(cmd), root, timeout)
    started = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            cwd=root,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        elapsed = time.monotonic() - started
        logger.error("%s timed out after %.1fs (limit %ss)", " ".join(cmd), elapsed, timeout)
        output = _as_text(exc.stdout) + _as_text(exc.stderr) + f"\n[pre-pr-gate] timed out after {timeout}s\n"
        return False, 124, output
    except (FileNotFoundError, NotADirectoryError, PermissionError) as exc:
        logger.error("could not run %s: %s", " ".join(cmd), exc)
        return False, 127, f"[pre-pr-gate] could not run `{' '.join(cmd)}` in {root}: {exc}\n"

    elapsed = time.monotonic() - started
    logger.info("%s exited %d in %.1fs", " ".join(cmd), proc.returncode, elapsed)
    return proc.returncode == 0, proc.returncode, proc.stdout + proc.stderr


def write_report(out_path: Path, *, passed: bool, exit_code: int, target: str, root: Path) -> None:
    report = {"passed": passed, "exit_code": exit_code, "target": target, "root": str(root)}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    logger.info("report written to %s", out_path)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".", help="directory to run `make` in (default: cwd)")
    ap.add_argument("--target", default=DEFAULT_TARGET, help=f"make target to invoke (default: {DEFAULT_TARGET})")
    ap.add_argument("--base-ref", default=None, help="override PRE_PR_BASE_REF (e.g. origin/main)")
    ap.add_argument("--out", default=None, help="write a JSON report to this path")
    ap.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"seconds before the gate is killed (default: {DEFAULT_TIMEOUT_SECONDS})",
    )
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    passed, exit_code, output = run_gate(root, args.target, args.base_ref, args.timeout)
    print(output)

    if args.out:
        write_report(Path(args.out), passed=passed, exit_code=exit_code, target=args.target, root=root)

    if passed:
        print(f"pre-pr-gate: OK - `make {args.target}` passed")
    else:
        print(f"pre-pr-gate: FAILED - `make {args.target}` exited {exit_code}")
    return exit_code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
