"""Shared fresh-interpreter probe runner for registry extraction.

Provides a unified `run_probe()` that handles OSError translation, TimeoutExpired
partial-stream capture, and non-zero exit formatting.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
PROBE_TIMEOUT_SECONDS = 30


def _as_stream_text(stream: str | bytes | None) -> str:
    """A captured stream rendered for a human, whatever shape it arrives in."""
    if stream is None:
        return ""
    if isinstance(stream, bytes):
        return stream.decode("utf-8", errors="replace")
    return stream


def run_probe(probe_args: list[str], *, timeout: int = PROBE_TIMEOUT_SECONDS, cwd: Path = _REPO_ROOT) -> str:
    """Run a fresh-interpreter probe.

    Translates OSError (e.g. missing interpreter), TimeoutExpired (with partial streams),
    and non-zero exits into clear RuntimeErrors with context.
    """
    logger.debug("probe: %s %s (cwd %s, timeout %ss)", sys.executable, " ".join(probe_args), cwd, timeout)
    try:
        completed = subprocess.run(
            [sys.executable, *probe_args],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
        )
    except OSError as exc:
        raise RuntimeError(f"probe could not start ({sys.executable!r}): {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"probe did not finish within {timeout}s\n"
            f"partial stdout:\n{_as_stream_text(exc.stdout)}\n"
            f"partial stderr:\n{_as_stream_text(exc.stderr)}"
        ) from exc

    if completed.returncode != 0:
        raise RuntimeError(
            f"probe failed (exit {completed.returncode})\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed.stdout
