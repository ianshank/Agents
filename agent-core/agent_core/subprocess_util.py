"""Fail-safe subprocess runner shared across agent_core.

A missing binary, an unrunnable one, a timeout, or undecodable output becomes a non-zero
:class:`subprocess.CompletedProcess` rather than an exception, so callers degrade to "no
signal observed" instead of crashing or hanging. The synthetic results reuse the
conventional shell exit codes (124 timeout, 127 not found, 126 found-but-not-executable).

Byte-oriented on purpose: text mode (``text=True``) translates ``\\n`` to ``\\r\\n`` on
Windows when writing stdin, corrupting git-plumbing input — e.g. a ``mktree`` line
``... blob <sha>\\t<name>\\n`` becomes ``...\\r\\n``, so the tree entry name ends up as
``<name>\\r`` and a later ``git show <tip>:<name>`` cannot find it. We therefore encode
stdin and decode stdout/stderr as UTF-8 ourselves (``errors="replace"``, so non-UTF-8
child output never raises ``UnicodeDecodeError``) — ``\\n`` stays ``\\n`` on every platform.

Extracted so the ``detectors`` and ``store_sync`` copies of this idiom cannot drift (they
had, and one had dropped both the warning logs and, later, the byte-oriented Windows fix).
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence

from .logging_util import get_logger

logger = get_logger(__name__)

# Conventional shell exit codes reused for the fail-safe synthetic results.
RC_TIMED_OUT = 124
RC_CANNOT_EXEC = 126  # found but not executable / not runnable (PermissionError, exec format)
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
        The completed process (with UTF-8-decoded ``stdout``/``stderr``), or a synthetic
        non-zero result carrying :data:`RC_NOT_FOUND` (missing binary),
        :data:`RC_CANNOT_EXEC` (present but not runnable), or :data:`RC_TIMED_OUT`
        (timeout). Never raises: stdin is byte-encoded (no newline translation), output is
        decoded with ``errors="replace"``, and every ``OSError`` becomes a synthetic result.
    """
    argv = list(args)
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            timeout=timeout,
            input=input_text.encode("utf-8") if input_text is not None else None,
        )
    except FileNotFoundError:
        logger.warning("executable not found: %s; degrading to 'no signal'", argv[0])
        return subprocess.CompletedProcess(argv, RC_NOT_FOUND, "", "executable not found")
    except subprocess.TimeoutExpired:
        logger.warning("%s timed out after %.1fs; degrading to 'no signal'", argv[0], timeout)
        return subprocess.CompletedProcess(argv, RC_TIMED_OUT, "", "timed out")
    except OSError as exc:
        # Present but unrunnable: PermissionError, exec-format error, etc. FileNotFoundError
        # is a subclass and is handled above, so this is the "cannot execute" bucket.
        logger.warning("cannot execute %s: %s; degrading to 'no signal'", argv[0], exc)
        return subprocess.CompletedProcess(argv, RC_CANNOT_EXEC, "", str(exc))
    return subprocess.CompletedProcess(
        argv,
        proc.returncode,
        proc.stdout.decode("utf-8", "replace"),
        proc.stderr.decode("utf-8", "replace"),
    )
