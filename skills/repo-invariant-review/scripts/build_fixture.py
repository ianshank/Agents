#!/usr/bin/env python3
"""Build a throwaway git repository that exercises the invariant checks.

The fixtures are *built*, not committed, for two reasons: a committed fixture repo would
need a nested ``.git`` directory (which the outer repo cannot track), and a violating
fixture must contain a file over the 500-line ceiling, which would itself trip the outer
repo's own size-budget gate.

Everything is deterministic — fixed content, fixed commit metadata, no timestamps — so the
reports built from these trees are byte-stable and the determinism eval is meaningful.
"""

from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("build-fixture")

#: Fixed identity + dates so the fixture's commit hash never varies.
_GIT_ENV = {
    "GIT_AUTHOR_NAME": "fixture",
    "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
    "GIT_COMMITTER_NAME": "fixture",
    "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00",
}

#: Enough of the real repo's sources of truth for the checker to read them, so the fixture
#: exercises the same code path as a real run rather than the fallback constants.
_PROTECTED_PATHS_STUB = '''"""Stub of the repo's protected-path source of truth.

Mirrors the real module's *interface*, not just its data: the skill loads ``is_protected``
from here and uses it directly, so a stub exposing only ``PROTECTED_PATTERNS`` would push
every test down the fallback path and leave the real matcher untested. The mid-path
wildcard below is deliberate — it is the case prefix-matching gets wrong.
"""

import re

PROTECTED_PATTERNS = (
    "features.yaml",
    "src/eval_harness/scorers/**",
    "tests/**",
    "skills/*/tests/**",
)


def _glob_to_regex(pattern):
    out = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


_COMPILED = tuple(_glob_to_regex(p) for p in PROTECTED_PATTERNS)


def is_protected(path):
    norm = path.strip().replace("\\\\", "/").lstrip("./").lstrip("/")
    return any(rx.match(norm) for rx in _COMPILED)
'''

_SIZE_BUDGET_STUB = '''"""Stub of the repo's size-budget gate."""

MAX_FILE_LINES = 500
'''

_BASELINE = '{\n  "packages": ["eval_harness"],\n  "surface": {}\n}\n'


def _run(args: list[str], cwd: Path) -> None:
    import os

    subprocess.run(args, cwd=cwd, check=True, capture_output=True, env={**os.environ, **_GIT_ENV})


def _write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _seed_common(root: Path) -> None:
    """Files present in both fixtures, committed as the baseline the diff runs against."""
    _write(root, "scripts/eval_protected_paths.py", _PROTECTED_PATHS_STUB)
    _write(root, "scripts/check_size_budget.py", _SIZE_BUDGET_STUB)
    _write(root, "tests/public_surface_baseline.json", _BASELINE)
    _write(root, "tests/plugin_registry_baseline.json", _BASELINE)
    _write(root, "README.md", "# fixture\n\n```\nsrc/eval_harness/\n  scorers/  exact_match\n```\n")
    _write(root, "src/eval_harness/README.md", "| `scorers/` | exact_match |\n")
    _write(root, "docs/CHARTER.md", "# Charter\n")


def build(kind: str, out: Path) -> Path:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    _run(["git", "init", "-q", "-b", "main"], out)
    _seed_common(out)
    _run(["git", "add", "-A"], out)
    _run(["git", "commit", "-q", "-m", "baseline"], out)

    if kind == "clean":
        # An unprotected doc-only change: nothing should fire.
        _write(out, "docs/notes.md", "a harmless note\n")
    else:
        # Three distinct collisions at once, so one eval covers several checks.
        _write(out, "features.yaml", "features: []\n")  # protected path
        _write(
            out,
            "src/eval_harness/scorers/huge.py",
            '"""Over the ceiling on purpose."""\n' + "x = 1\n" * 600,  # size budget + protected
        )
        _write(
            out,
            "src/eval_harness/scorers/crosser.py",
            '"""Crosses the airgap on purpose."""\n\nfrom flow_corpus.oracles import kappa_gate\n',
        )
    _run(["git", "add", "-A"], out)
    logger.debug("fixture %s built at %s", kind, out)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--kind", choices=("clean", "violating"), required=True)
    parser.add_argument("--out", required=True, help="directory to build the fixture repo in")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-8s %(name)s: %(message)s",
    )
    path = build(args.kind, Path(args.out).resolve())
    print(f"build-fixture: {args.kind} fixture ready at {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
