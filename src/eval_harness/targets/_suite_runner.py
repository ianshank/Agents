#!/usr/bin/env python3
"""Run one generated test suite against one focal implementation, and report JSON.

Executed as a SUBPROCESS by ``targets/testgen.py`` — never imported by the harness. That
separation is the whole point: this file is the only place model-authored test code runs,
and it runs in its own interpreter so a wall-clock limit can actually terminate it. An
in-process runner could not be timed out (a `while True` in a generated test would hang the
harness), and could not be prevented from mutating the harness's own module state.

Deliberately dependency-free — stdlib only, no pytest. The harness must not acquire a
runtime test-framework dependency to score test suites, and collection here is a dozen
lines: import the module, take its ``test_*`` callables in definition order, call each.

Protocol, because two files must agree on it:

    argv:    <workdir>
    workdir: focal.py + suite.py, written by the caller
    result:  <workdir>/result.json — one JSON object (the schema in `_report`)
    error:   <workdir>/runner_error.txt — a traceback, only when the runner itself broke
    exit:    0 whether tests passed or failed. A failing test is data, not an error.

The verdict travels through a FILE, not stdout, and that is the whole point of this
paragraph. A generated test calling ``print()`` is completely ordinary — model-authored
suites do it constantly — and an earlier cut of this runner returned its JSON on stdout,
so any such suite corrupted the payload and was scored NON-EXECUTABLE. A perfectly good
suite failed for writing to a channel it had every right to write to. The protocol must
not share a channel with the code under test.

The caller therefore discards the sandbox's stdout and stderr entirely, which also removes
an unbounded-memory path: a suite printing in a loop can no longer be buffered into the
harness's address space.

``focal.py`` is expected to expose ``__calls__``, a list the caller's instrumentation
appends to. Recording which inputs the suite actually drove is what makes the *normalized*
mutation denominator ("of what it reached") decidable without coverage instrumentation.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import sys
import traceback
from pathlib import Path
from typing import Any

#: Filenames the two sides exchange through the sandbox directory. Named here and imported
#: by the caller so the two cannot drift.
FOCAL_FILENAME = "focal.py"
SUITE_FILENAME = "suite.py"
RESULT_FILENAME = "result.json"
RUNNER_ERROR_FILENAME = "runner_error.txt"

#: Prefix a callable must carry to be collected as a test. The pytest convention, so a
#: model-authored suite written for pytest collects here unchanged.
TEST_PREFIX = "test_"


def _load(path: Path, name: str) -> Any:
    """Import *path* as a module named *name*, raising on any failure."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - unreachable for a real file
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _report(workdir: Path) -> dict[str, Any]:
    """Collect and run, returning the payload the caller parses."""
    sys.path.insert(0, str(workdir))
    focal = _load(workdir / FOCAL_FILENAME, "focal")

    try:
        suite = _load(workdir / SUITE_FILENAME, "suite")
    except BaseException as exc:
        # Collection failure is a first-class outcome, not a runner error: the spec
        # separates "did not import" from "imported and failed", and only the first makes
        # the other three scorers not-applicable.
        return {
            "collected": 0,
            "collection_error": f"{type(exc).__name__}: {exc}",
            "passed": [],
            "failed": [],
            "calls": list(getattr(focal, "__calls__", [])),
        }

    tests = [
        (name, getattr(suite, name))
        for name in dir(suite)
        if name.startswith(TEST_PREFIX) and callable(getattr(suite, name))
    ]
    tests.sort(key=lambda pair: pair[0])

    passed: list[str] = []
    failed: list[str] = []
    for name, fn in tests:
        try:
            fn()
        except BaseException:
            failed.append(name)
        else:
            passed.append(name)

    return {
        "collected": len(tests),
        "collection_error": None,
        "passed": passed,
        "failed": failed,
        "calls": list(getattr(focal, "__calls__", [])),
    }


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: _suite_runner.py <workdir>", file=sys.stderr)
        return 2
    workdir = Path(args[0])
    try:
        payload = _report(workdir)
    except Exception:  # the runner itself broke; the caller must not read this as a verdict
        # An unwritable workdir is itself the failure; the exit code carries it, and the
        # caller reports "no detail" rather than crashing on the missing file.
        with contextlib.suppress(OSError):
            (workdir / RUNNER_ERROR_FILENAME).write_text(traceback.format_exc(), encoding="utf-8")
        return 1
    (workdir / RESULT_FILENAME).write_text(json.dumps(payload), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
