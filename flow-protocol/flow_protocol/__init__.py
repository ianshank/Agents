"""flow-protocol: the versioned contract surface across the corpus/harness airgap.

Both the corpus and the harness may import this package; neither may import the
other's internals. Keeping the shared surface to these few types is what makes the
airgap structural (enforced in CI by the architecture-drift gate).
"""

from __future__ import annotations

from .contract import ConfidenceChannel, FlowResult, OracleResult, OracleTier
from .version import PROTOCOL_VERSION, __version__, migrate_protocol

__all__ = [
    "PROTOCOL_VERSION",
    "ConfidenceChannel",
    "FlowResult",
    "OracleResult",
    "OracleTier",
    "__version__",
    "migrate_protocol",
]
