"""Injectable subprocess runner so every external command is fake-able in unit tests.

All docker/git invocations in this package go through a ``CommandRunner`` — the same
dependency-injection discipline the repo uses for SDK clients (Null doubles). Nothing
here raises on non-zero exit: callers decide what a failure means; a timeout is data
(``timed_out=True``), not an exception.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class CompletedCommand:
    argv: tuple[str, ...]
    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


class CommandRunner(Protocol):
    def run(
        self,
        argv: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> CompletedCommand: ...


class SubprocessRunner:
    """The real runner; the only place this package touches ``subprocess``."""

    def run(
        self,
        argv: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> CompletedCommand:
        try:
            proc = subprocess.run(
                argv,
                cwd=str(cwd) if cwd else None,
                env=env,
                timeout=timeout,
                capture_output=True,
                text=True,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            return CompletedCommand(tuple(argv), returncode=-1, stdout=stdout, stderr=stderr, timed_out=True)
        except OSError as exc:
            return CompletedCommand(tuple(argv), returncode=-1, stderr=str(exc))
        return CompletedCommand(tuple(argv), proc.returncode, proc.stdout, proc.stderr)
