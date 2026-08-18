#!/usr/bin/env python3
"""Seed a scratch copy of the fixture repo and perform the *first* compose pass.

The eval's own ``run`` command then performs only the *second* compose pass, against the
same scratch repo, so the eval's assertions can prove append-not-overwrite against real,
on-disk output from two real subprocess invocations of ``scripts/run.py`` -- not a
simulation.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parents[2]
SCRATCH = SKILL_DIR / ".skill-validation" / "compose-append-repo"

shutil.rmtree(SCRATCH, ignore_errors=True)
shutil.copytree(HERE / "repo", SCRATCH)

subprocess.run(
    [
        sys.executable,
        str(SKILL_DIR / "scripts" / "run.py"),
        "compose",
        "--repo",
        str(SCRATCH),
        "--change",
        "demo-change",
        "--body-file",
        str(HERE / "body1.md"),
        "--tree-sha",
        "aaa111firstpass",
        "--dispatch-path",
        "degraded",
    ],
    cwd=SKILL_DIR,
    check=True,
)
