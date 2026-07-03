#!/usr/bin/env python3
"""model-bench skill runner.

A thin, packaged entrypoint over the eval-harness multi-model comparison (F-024)
and A/B eval campaign (F-025) features. It does not re-implement any orchestration
— it forwards to the already-built, already-tested ``eval-harness`` CLI
subcommands ``compare`` and ``campaign`` (which reuse ``run_comparison`` /
``record_run`` / ``analyze`` under the hood). With the real model-backed target
(F-027) available, the same configs can benchmark live models; the bundled
fixtures use deterministic ``echo`` targets so the skill's evals run offline.

Usage:
    run.py compare  --config <eval.yaml> [--offline] [--html OUT] [--json OUT]
    run.py campaign --config <eval.yaml> --store <store.jsonl>
                    [--mode record|analyze] [--offline] [--html OUT] [--json OUT]
"""

from __future__ import annotations

import sys

_SUBCOMMANDS = ("compare", "campaign")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in _SUBCOMMANDS:
        print(
            "usage: run.py {compare|campaign} --config <eval.yaml> [...]\n"
            "  compare  : rank several models on one dataset (config 'comparison' block)\n"
            "  campaign : record/analyze an A/B campaign (config 'ab_campaign' block)",
            file=sys.stderr,
        )
        return 2

    try:
        from eval_harness.cli import main as harness_main
    except ImportError:
        print(
            "ERROR: langfuse-eval-harness must be installed to run model-bench (pip install -e . from the repo root).",
            file=sys.stderr,
        )
        return 1

    # Forward verbatim to the harness CLI — it owns arg parsing and the work.
    exit_code: int = harness_main(argv)
    return exit_code


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    sys.exit(main())
