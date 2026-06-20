"""Two-way version-pin verification (the airgap's skew tripwire).

``verify_pins`` reads the *live* ``flow_protocol`` and ``agent_core`` versions and
compares them to what this corpus build pinned. A mismatch raises
:class:`PinMismatchError` so the build fails immediately rather than producing keyed
population stats against an unexpected contract.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_core.logging_util import get_logger
from flow_protocol.version import PROTOCOL_VERSION

from .version import HARNESS_VERSION_PIN, PROTOCOL_VERSION_PIN

_log = get_logger("flow_corpus.pinning")


class PinMismatchError(RuntimeError):
    """Raised when a live dependency version differs from the corpus's pin."""


@dataclass(frozen=True)
class PinReport:
    protocol_expected: str
    protocol_actual: str
    harness_expected: str
    harness_actual: str

    @property
    def ok(self) -> bool:
        return (
            self.protocol_expected == self.protocol_actual
            and self.harness_expected == self.harness_actual
        )


def _live_harness_version() -> str:
    """Live agent_core distribution version (imported lazily to keep this module light)."""
    from agent_core.version import __version__ as harness_version

    return str(harness_version)


def check_pins() -> PinReport:
    """Return a :class:`PinReport` comparing pinned vs live versions (no raising)."""
    return PinReport(
        protocol_expected=PROTOCOL_VERSION_PIN,
        protocol_actual=PROTOCOL_VERSION,
        harness_expected=HARNESS_VERSION_PIN,
        harness_actual=_live_harness_version(),
    )


def verify_pins() -> PinReport:
    """Raise :class:`PinMismatchError` if either live version differs from its pin."""
    report = check_pins()
    if not report.ok:
        _log.error(
            "version pin mismatch protocol_expected=%s protocol_actual=%s "
            "harness_expected=%s harness_actual=%s",
            report.protocol_expected,
            report.protocol_actual,
            report.harness_expected,
            report.harness_actual,
        )
        raise PinMismatchError(
            "flow-corpus version pin mismatch: "
            f"protocol expected {report.protocol_expected!r} got {report.protocol_actual!r}; "
            f"harness expected {report.harness_expected!r} got {report.harness_actual!r}. "
            "Bump the pins in flow_corpus.version deliberately when adopting a new version."
        )
    return report
