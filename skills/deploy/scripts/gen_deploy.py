#!/usr/bin/env python3
"""Generate a deterministic, safety-railed deployment script for a project.

  python scripts/gen_deploy.py --app mysvc --artifact registry/mysvc:1.2.3 \\
      --health-url https://mysvc.example.com/healthz --environment production

  python scripts/gen_deploy.py --stdout        # print instead of writing
  python scripts/gen_deploy.py --check         # advisory: exit 1 if the committed script is stale

The emitted ``deploy.sh`` supplies the safety structure (strict mode, --dry-run, a confirmation
gate, rollback, a health-check retry loop); you fill in the per-step commands. Secrets are read
from the environment at run time and are never written into the script.

Exit codes: 0 success (or ``--check`` up to date); 1 ``--check`` drift / missing.
"""

from __future__ import annotations

import argparse
import logging
import stat
import sys
from pathlib import Path

from deploygen import DeployConfig, render_deploy

logger = logging.getLogger("deploygen")


def _check(out: Path, content: str) -> int:
    """Advisory freshness check: compare the committed script against a fresh render."""
    if not out.is_file():
        print(f"[drift] {out.as_posix()} is missing; run the deploy skill to create it")
        return 1
    if out.read_text(encoding="utf-8") == content:
        print(f"{out.as_posix()} is up to date")
        return 0
    print(f"[drift] {out.as_posix()} is stale; regenerate with the deploy skill")
    return 1


def _make_executable(path: Path) -> None:
    """chmod +x (u+g+o) so the script can be run directly; mode is not file content."""
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a safety-railed deployment script.")
    parser.add_argument("--root", default=".", help="Project root (default output is <root>/scripts/deploy.sh).")
    parser.add_argument("--app", default="app", help="Application name (used in logs and rollback).")
    parser.add_argument("--environment", default="production", help="Target environment name.")
    parser.add_argument("--artifact", default="<artifact>", help="Artifact/image reference to deploy.")
    parser.add_argument("--health-url", default="<health-url>", dest="health_url", help="Health-check URL.")
    parser.add_argument("--out", default=None, help="Output path (default: <root>/scripts/deploy.sh).")
    parser.add_argument("--stdout", action="store_true", help="Print the script instead of writing it.")
    parser.add_argument("--check", action="store_true", help="Advisory: exit 1 if the committed script is stale.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging (prints the deploy config).")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    config = DeployConfig(
        app=args.app,
        environment=args.environment,
        artifact=args.artifact,
        health_url=args.health_url,
    )
    logger.debug("deploy config: %s", config)
    content = render_deploy(config)

    if args.stdout:
        sys.stdout.write(content)
        return 0

    out = Path(args.out) if args.out else Path(args.root) / "scripts" / "deploy.sh"
    if args.check:
        return _check(out, content)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8", newline="\n")
    _make_executable(out)
    print(f"wrote {out.as_posix()}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
