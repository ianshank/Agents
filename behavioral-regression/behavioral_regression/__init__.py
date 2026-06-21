"""behavioral-regression: a calibrated, offline behavioural-regression detector.

Answers a contested behavioural question — "did model v2 drift (e.g. more sycophantic)
vs v1?" — with a calibrated probability and an interval, validates its own judge against
human labels before trusting it, surfaces an explicit "can't tell" bucket, and gates
SHIP / HOLD / ESCALATE (fail-safe-to-escalate).

Dependency direction: this package imports ``agent_core`` (calibration / metric
primitives), ``flow_corpus`` (oracle-κ gate, bootstrap delta CI, canary separation,
Brier reliability), and ``flow_protocol`` only — never ``eval_harness``. The optional
live judge lives in ``eval_harness.judges`` and is wired in by the harness layer; this
package stays offline.
"""

from __future__ import annotations

from .canary import CanaryReport, run_canary
from .config import BRConfig, ConfigError
from .detector import RegressionDetector, RegressionEstimate
from .gate import ShipDecision, decide_ship
from .generator import PairedResponse, PairedResponseGenerator
from .judge import JudgeProtocol, JVerdict, SyntheticJudge
from .oracle import validate_judge
from .pipeline import run_pipeline
from .report import RegressionReport
from .version import SCHEMA_VERSION, __version__

__all__ = [
    "SCHEMA_VERSION",
    "BRConfig",
    "CanaryReport",
    "ConfigError",
    "JVerdict",
    "JudgeProtocol",
    "PairedResponse",
    "PairedResponseGenerator",
    "RegressionDetector",
    "RegressionEstimate",
    "RegressionReport",
    "ShipDecision",
    "SyntheticJudge",
    "__version__",
    "decide_ship",
    "run_canary",
    "run_pipeline",
    "validate_judge",
]
