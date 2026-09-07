"""Sandbox boundary for the testgen suite-execution target (ADR 0045).

The parent-side half of the sandbox: what the child interpreter may see. The child half
is ``_suite_runner.py``, which applies the resource limits carried in these environment
variables to itself before loading any model-authored code.

Two invariants live here:

* **Default-deny environment.** The child inherits only the allowlisted plumbing
  variables, so generated code cannot read the harness process's credentials
  (``OPENAI_API_KEY``, ``ANTHROPIC_API_KEY``, ``LANGFUSE_*``, ``AWS_*``). The allowlist
  is a module constant, not config: an operator override would be a way to widen what
  generated code can see, which ADR 0045 says must not be config-driven.
* **Env-carried limits, not ``preexec_fn``.** ``preexec_fn`` runs between fork and exec,
  which is unsafe under the engine's threaded item execution (``max_workers > 1``);
  limits carried in the environment keep the fork path lock-free.
"""

from __future__ import annotations

import functools
import importlib.util
import logging
import math
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

#: Environment variables the sandboxed interpreter is allowed to inherit. PATH/HOME/
#: TMPDIR keep the interpreter and stdlib tempfile working; SYSTEMROOT is required for
#: some Windows APIs.
CHILD_ENV_ALLOWLIST: tuple[str, ...] = (
    "PATH",
    "HOME",
    "TMPDIR",
    "TEMP",
    "TMP",
    "SYSTEMROOT",
    "LANG",
    "LC_ALL",
)

#: Env-var names that carry the resource limits to the runner. The runner reads them at
#: startup (before loading the suite), so the limits bind the interpreter that executes
#: model-authored code.
RLIMIT_ENV_CPU = "EVAL_HARNESS_TESTGEN_RLIMIT_CPU"
RLIMIT_ENV_AS = "EVAL_HARNESS_TESTGEN_RLIMIT_AS"
RLIMIT_ENV_NPROC = "EVAL_HARNESS_TESTGEN_RLIMIT_NPROC"
RLIMIT_ENV_FSIZE = "EVAL_HARNESS_TESTGEN_RLIMIT_FSIZE"
RLIMIT_ENV_NOFILE = "EVAL_HARNESS_TESTGEN_RLIMIT_NOFILE"


@dataclass(frozen=True)
class SandboxLimits:
    """Resource limits applied to the sandboxed suite interpreter (POSIX only).

    The wall-clock timeout remains the primary bound; these close the holes it cannot:
    a CPU-bound loop, a memory hog, a fork bomb, and unbounded file writes. On platforms
    without the ``resource`` module the runner logs the degradation and relies on the
    timeout alone. ``cpu_seconds=None`` derives the CPU ceiling from the execution's own
    timeout plus ``cpu_margin_seconds``, so a per-item ``timeout_seconds`` override
    tightens both bounds together.
    """

    cpu_seconds: int | None = None  # derive from the execution timeout when None
    cpu_margin_seconds: int = 5  # headroom above the wall timeout for the CPU ceiling
    memory_bytes: int = 2 * 1024**3  # address-space cap; generous for pure-Python suites
    max_processes: int = 0  # no fork/thread spawn inside the sandbox (fork-bomb defense)
    max_file_bytes: int = 64 * 1024**2  # per-file write cap inside the sandbox
    max_open_files: int = 256  # fd ceiling; suites open focal.py/suite.py and little else

    def cpu_ceiling(self, timeout: float) -> int:
        """The CPU-time ceiling for one execution, derived from its wall-clock timeout."""
        if self.cpu_seconds is not None:
            return self.cpu_seconds
        return math.ceil(timeout) + self.cpu_margin_seconds


@functools.lru_cache(maxsize=1)
def warn_if_limits_unavailable() -> bool:
    """Log once when this platform has no ``resource``, and report whether it does.

    The child logs its own degradation to stderr, but the parent runs it with
    ``stderr=DEVNULL``, so on Windows that notice reached nobody and the sandbox
    silently narrowed to the wall-clock timeout alone. Parent and child are the same
    host, so the parent can answer this itself. ``lru_cache`` keeps it to one line
    per process rather than one per item.
    """
    available = importlib.util.find_spec("resource") is not None
    if not available:
        logger.warning(
            "testgen sandbox: the resource module is unavailable on this platform; "
            "CPU, memory, process and file-size limits are not applied and the "
            "wall-clock timeout is the only bound"
        )
    return available


def sandbox_child_env(limits: SandboxLimits, timeout: float) -> dict[str, str]:
    """The scrubbed environment the sandboxed interpreter runs with.

    Only the allowlisted plumbing variables are inherited; the RLIMIT entries hand the
    resource limits to the runner.
    """
    env = {name: os.environ[name] for name in CHILD_ENV_ALLOWLIST if name in os.environ}
    env["PYTHONUTF8"] = "1"
    env[RLIMIT_ENV_CPU] = str(limits.cpu_ceiling(timeout))
    env[RLIMIT_ENV_AS] = str(limits.memory_bytes)
    env[RLIMIT_ENV_NPROC] = str(limits.max_processes)
    env[RLIMIT_ENV_FSIZE] = str(limits.max_file_bytes)
    env[RLIMIT_ENV_NOFILE] = str(limits.max_open_files)
    return env
