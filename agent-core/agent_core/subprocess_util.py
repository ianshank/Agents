"""Fail-safe subprocess runner shared across agent_core.

A missing binary or a timeout becomes a non-zero :class:`subprocess.CompletedProcess`
rather than an exception, so callers degrade to "no signal observed" instead of crashing
or hanging. The synthetic results reuse the conventional shell exit codes (124 for a
timeout, 127 for a missing executable). Extracted so the ``detectors`` and ``store_sync``
copies of this idiom cannot drift (they had, and one had dropped the warning logs).
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence

from .logging_util import get_logger

logger = get_logger(__name__)

# Conventional shell exit codes reused for the fail-safe synthetic results.
RC_TIMED_OUT = 124
RC_NOT_FOUND = 127


def run_failsafe(
    args: Sequence[str], timeout: float, input_text: str | None = None
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess without ever raising or hanging.

    Args:
        args: The command and its arguments.
        timeout: Hard wall-clock bound in seconds.
        input_text: Optional stdin payload (used by git plumbing).

    Returns:
        The completed process, or a synthetic non-zero result carrying
        :data:`RC_NOT_FOUND` / :data:`RC_TIMED_OUT` when the binary is missing or times out.
    """
    argv = list(args)
    try:
        return subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, input=input_text
        )
    except FileNotFoundError:
        logger.warning("executable not found: %s; degrading to 'no signal'", argv[0])
        return subprocess.CompletedProcess(argv, RC_NOT_FOUND, "", "executable not found")
    except subprocess.TimeoutExpired:
        logger.warning("%s timed out after %.1fs; degrading to 'no signal'", argv[0], timeout)
        return subprocess.CompletedProcess(argv, RC_TIMED_OUT, "", "timed out")
