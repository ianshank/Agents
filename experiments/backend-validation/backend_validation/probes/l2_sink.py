"""L2 integration probes — the ONLY module that imports the eval harness (spec R1/R4).

Answers "what does adoption cost", strictly at the vendor-neutral sink surface the harness
actually exposes today: ``eval_harness.core.interfaces.ResultSink`` + ``RunResult``. There
is NO unified tracer/experiment/backend abstraction in the harness (the recon finding), so
anything below the sink surface is reported BLOCKED-scope, never improvised into existence.

The experiment-local ``OpikSink`` is itself the adapter-delta metric: writing it here (not
in ``src/eval_harness``) measures exactly what adopting Opik would cost. Langfuse already
ships a ``ResultSink`` in the harness, so its adapter delta is zero.

Import discipline: the harness imports live INSIDE functions / are guarded so that merely
importing this module never drags ``eval_harness`` in — the precondition check decides
whether L2 can run at all.
"""

from __future__ import annotations

import importlib
import importlib.util
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from backend_validation.logging_util import get_logger

logger = get_logger(__name__)

# The vendor-neutral seam L2 targets. If any of these cannot be imported, L2 is BLOCKED —
# the harness's core Protocols do not exist yet and comparing adapters would be meaningless.
_REQUIRED_SEAMS = (
    ("eval_harness.core.interfaces", "ResultSink"),
    ("eval_harness.core.types", "RunResult"),
    ("eval_harness.gating", "evaluate_gate"),
)


@dataclass(frozen=True)
class PreconditionResult:
    ok: bool
    missing: tuple[str, ...] = ()
    detail: str = ""


def check_precondition() -> PreconditionResult:
    """Verify the harness sink seam is importable WITHOUT importing it into this namespace."""
    missing: list[str] = []
    for module_name, attribute in _REQUIRED_SEAMS:
        spec = importlib.util.find_spec(module_name)
        if spec is None:
            missing.append(f"{module_name} (module not importable)")
            continue
        module = importlib.import_module(module_name)
        if not hasattr(module, attribute):
            missing.append(f"{module_name}.{attribute} (attribute absent)")
    if missing:
        return PreconditionResult(
            ok=False,
            missing=tuple(missing),
            detail="the harness's vendor-neutral sink seam is not importable; below-sink L2 is out of scope",
        )
    return PreconditionResult(ok=True)


# --- ADAPTER-DELTA-START (everything between the sentinels is the cost of adopting Opik
# at the sink surface; Langfuse's equivalent already ships in the harness, delta 0) ---
class OpikScoreClient(Protocol):
    """Narrow score-write surface the OpikSink drives; faked in tests, SDK-backed live."""

    def log_score(self, *, run_id: str, item_id: str, name: str, value: float, comment: str | None) -> None: ...

    def flush(self) -> None: ...


@dataclass
class NullOpikScoreClient:
    """Recording double mirroring eval_harness.langfuse_client.NullLangfuseClient."""

    scores: list[dict[str, Any]] = field(default_factory=list)
    flushed: int = 0

    def log_score(self, *, run_id: str, item_id: str, name: str, value: float, comment: str | None) -> None:
        self.scores.append({"run_id": run_id, "item_id": item_id, "name": name, "value": value, "comment": comment})

    def flush(self) -> None:
        self.flushed += 1


def build_opik_sink(client: OpikScoreClient, *, min_value_to_log: float | None = None) -> Any:
    """Construct an ``OpikSink(ResultSink)`` bound to ``client``.

    The class is defined here (inside the function) so importing this module never requires
    the harness; the precondition check gates whether we ever get here.
    """
    from eval_harness.core.interfaces import ResultSink
    from eval_harness.core.types import RunResult

    class OpikSink(ResultSink):
        """Vendor-neutral sink for Opik — the adapter whose delta L2 measures.

        Deliberately mirrors ``eval_harness.sinks.LangfuseSink.emit`` operation-for-
        operation (per-item, per-score ``log_score`` then a single ``flush``) so the
        conformance probe compares like with like."""

        def __init__(self, opik_client: OpikScoreClient, threshold: float | None) -> None:
            self._client = opik_client
            self._min_value_to_log = threshold

        def emit(self, run: RunResult) -> None:
            for item_result in run.items:
                for score in item_result.scores:
                    if self._min_value_to_log is not None and score.value < self._min_value_to_log:
                        continue
                    self._client.log_score(
                        run_id=run.run_id,
                        item_id=item_result.item.id,
                        name=score.name,
                        value=score.value,
                        comment=score.comment,
                    )
            self._client.flush()

    return OpikSink(client, min_value_to_log)


# --- ADAPTER-DELTA-END ---

_DELTA_START = "# --- ADAPTER-DELTA-START"
_DELTA_END = "# --- ADAPTER-DELTA-END ---"


def adapter_delta_loc(module_path: Path | None = None) -> int:
    """Count the Opik adapter's effective lines (non-blank, non-comment) between the
    sentinels — the concrete cost of adopting Opik at the sink surface. Measured from
    source so the number can never drift from the code (no hardcoded value)."""
    path = module_path if module_path is not None else Path(__file__)
    counted = 0
    inside = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(_DELTA_END):
            break
        if line.startswith(_DELTA_START):
            inside = True
            continue
        stripped = line.strip()
        if inside and stripped and not stripped.startswith("#"):
            counted += 1
    return counted
