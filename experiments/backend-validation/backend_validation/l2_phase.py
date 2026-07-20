"""P3 integration phase: drive the harness sink seam, measure adapter delta, or BLOCK.

Precondition-gated (spec R4): if the harness's vendor-neutral sink seam is not importable,
this writes a BLOCKED report and stops — it never fabricates a Protocol. When the seam is
present, it runs a conformance check (both sinks must emit the same logical score set from
one ``RunResult``) and a gate-ingestion check (a backend-shaped ``RunResult`` flows through
``evaluate_gate``), and records the Opik adapter delta into ``effort_metrics.json``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from backend_validation.logging_util import get_logger
from backend_validation.phases import STATUS_BLOCKED, STATUS_FAIL, STATUS_OK, PhaseResult, write_blocked_report
from backend_validation.probes.l2_sink import (
    NullOpikScoreClient,
    adapter_delta_loc,
    build_opik_sink,
    check_precondition,
)
from backend_validation.settings import Settings

logger = get_logger(__name__)


def _canonical_run(now_fn: Callable[[], str]) -> Any:
    """A fixed two-item, two-score RunResult — the conformance/ingestion fixture."""
    from datetime import datetime

    from eval_harness.core.types import EvalItem, ItemResult, RunResult, ScoreAggregate, ScoreResult, TargetOutput

    def _item(item_id: str, faith: float, rel: float) -> ItemResult:
        return ItemResult(
            item=EvalItem(id=item_id, inputs={"q": item_id}, expected="e"),
            output=TargetOutput(output="o", latency_ms=1.0),
            scores=[
                ScoreResult(name="faithfulness", value=faith, passed=faith >= 0.5, comment="c"),
                ScoreResult(name="relevancy", value=rel, passed=rel >= 0.5),
            ],
        )

    stamp = datetime.fromisoformat(now_fn())
    return RunResult(
        run_id="bv-l2-run",
        config_name="bv-l2",
        items=[_item("a", 0.9, 0.8), _item("b", 0.4, 0.7)],
        aggregate={
            "faithfulness": ScoreAggregate(count=2, mean=0.65, pass_rate=0.5),
            "relevancy": ScoreAggregate(count=2, mean=0.75, pass_rate=1.0),
        },
        started_at=stamp,
        finished_at=stamp,
    )


def _langfuse_scorecalls(run: Any) -> list[dict[str, Any]]:
    from eval_harness.langfuse_client import NullLangfuseClient
    from eval_harness.sinks import LangfuseSink

    client = NullLangfuseClient()
    sink = LangfuseSink()
    sink.attach_client(client)
    sink.emit(run)
    return [{"item_id": s["item_id"], "name": s["name"], "value": s["value"]} for s in client.scores]


def _opik_scorecalls(run: Any) -> list[dict[str, Any]]:
    client = NullOpikScoreClient()
    build_opik_sink(client).emit(run)
    return [{"item_id": s["item_id"], "name": s["name"], "value": s["value"]} for s in client.scores]


def _gate_ingestion_ok(run: Any) -> bool:
    """A backend-shaped RunResult must flow through the merge-gate report path."""
    from eval_harness.config.models import GateConfig, GateRule
    from eval_harness.gating import evaluate_gate

    gate = GateConfig(rules=[GateRule(score="faithfulness", metric="mean", min=0.5)])
    result = evaluate_gate(gate, run)
    failing = evaluate_gate(GateConfig(rules=[GateRule(score="faithfulness", metric="mean", min=0.99)]), run)
    # to_dict must also round-trip (it is what JsonFileSink writes for a CI gate to read).
    json.dumps(run.to_dict())
    return result.passed and not failing.passed


def run_l2(
    subtree_root: Path,
    settings: Settings,
    *,
    run_id: str,
    now_fn: Callable[[], str],
) -> PhaseResult:
    artifacts_dir = settings.resolve_dir("artifacts_dir", subtree_root)
    reports_dir = settings.resolve_dir("reports_dir", subtree_root)
    precondition = check_precondition()
    if not precondition.ok:
        report = write_blocked_report(
            artifacts_dir,
            run_id,
            "l2 (P3)",
            list(precondition.missing),
            "The harness's vendor-neutral sink seam (ResultSink + RunResult) must be importable "
            "before integration probes are meaningful. Install the harness (`pip install -e ../../`) "
            "or, if the core Protocols genuinely do not exist yet, that is migration-plan scope — "
            "below-sink L2 stays out of scope (spec R4).",
            now_fn=now_fn,
        )
        return PhaseResult("l2", STATUS_BLOCKED, precondition.detail, artifacts=(str(report),))

    run = _canonical_run(now_fn)
    langfuse_calls = _langfuse_scorecalls(run)
    opik_calls = _opik_scorecalls(run)
    conformant = langfuse_calls == opik_calls
    ingestion_ok = _gate_ingestion_ok(run)
    opik_loc = adapter_delta_loc()  # read the source once; reused below

    adapter_report = {
        "schema_version": 1,
        "adapter_delta": [
            {
                "backend": "langfuse",
                "adapter_files": 0,
                "adapter_loc": 0,
                "conformance_passed": int(conformant),
                "conformance_total": 1,
                "mapping_gaps": [] if conformant else ["langfuse/opik score-call sequences diverge"],
            },
            {
                "backend": "opik",
                "adapter_files": 1,
                "adapter_loc": opik_loc,
                "conformance_passed": int(conformant),
                "conformance_total": 1,
                "mapping_gaps": [] if conformant else ["opik sink emits a different score set than the harness sink"],
            },
        ],
        "gate_ingestion_ok": ingestion_ok,
    }
    out_path = reports_dir / "l2_adapter_delta.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(adapter_report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    logger.info("l2: conformant=%s ingestion_ok=%s opik_adapter_loc=%d", conformant, ingestion_ok, opik_loc)

    if not conformant:
        return PhaseResult(
            "l2", STATUS_FAIL, "Opik sink is not conformant with the harness sink surface", artifacts=(str(out_path),)
        )
    if not ingestion_ok:
        return PhaseResult(
            "l2", STATUS_FAIL, "backend RunResult did not flow through evaluate_gate", artifacts=(str(out_path),)
        )
    return PhaseResult(
        "l2",
        STATUS_OK,
        f"sink conformance OK; Opik adapter delta = 1 file / {opik_loc} LOC; gate ingestion OK",
        artifacts=(str(out_path),),
    )
