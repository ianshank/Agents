"""flow-corpus: a calibration corpus of agentic flow variants.

Owns specimens, task suites, oracles, the mutation engine, version keying, the
holdout/rotation manager, the discrimination canary, and the validation runner.

Airgap rule: this package imports ``flow_protocol`` (the shared contract) and
``agent_core`` (the reused metric/gate primitives) ONLY. It must never import
``eval_harness``; the architecture-drift gate enforces that mechanically.
"""

from __future__ import annotations

from .pinning import PinMismatchError, PinReport, check_pins, verify_pins
from .version import HARNESS_VERSION_PIN, PROTOCOL_VERSION_PIN, __version__

__all__ = [
    "HARNESS_VERSION_PIN",
    "PROTOCOL_VERSION_PIN",
    "PinMismatchError",
    "PinReport",
    "__version__",
    "check_pins",
    "verify_pins",
]
