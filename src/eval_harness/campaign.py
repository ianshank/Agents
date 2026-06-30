"""Persistent A/B eval campaigns with statistical significance (F-025).

An A/B campaign runs two arms (reusing the F-024 ``ModelSpec`` and the same
per-arm "run the base config with the target swapped" pattern) over the same
dataset/scorers, accumulating per-arm pass/total counts for a chosen score across
many runs in an append-only store. Significance is decided from agent_core's
Wilson intervals — reused, never reimplemented — and is **never claimed below the
configured power floor** (mirrors the behavioral-regression honesty convention:
emit an explicit "can't tell" rather than a false positive).

Reuse:
  * ``ModelSpec`` + the per-arm run pattern from :mod:`eval_harness.comparison` (F-024).
  * ``agent_core.calibration.wilson_interval`` for the per-arm CIs (the permitted
    eval_harness -> agent_core edge).
  * An append-only JSONL store on the same pattern as agent_core's OutcomeStore
    (agent_core's persistence is shape-specific to CycleState/Calibrator, so a
    purpose-shaped store is the right reuse, not the serializer).

Additive and opt-in: ``SCHEMA_VERSION`` is unchanged and the single-run path is
untouched.
"""

from __future__ import annotations

import html as _html
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from .config.models import ABCampaignConfig, EvalConfig, ModelSpec
from .core.types import RunResult
from .langfuse_client import LangfuseClient


class Decision(str, Enum):
    B_BETTER = "b_better"  # arm B significantly beats arm A
    A_BETTER = "a_better"  # arm A significantly beats arm B
    NO_DIFFERENCE = "no_difference"  # powered, but CIs overlap -> not demonstrably different
    CANT_TELL = "cant_tell"  # below the power floor -> no claim


@dataclass(frozen=True)
class CampaignRecord:
    campaign_id: str
    arm: str
    score: str
    successes: int
    n: int
    ts: str  # ISO-8601

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)

    @staticmethod
    def from_json(line: str) -> CampaignRecord:
        return CampaignRecord(**json.loads(line))


class CampaignStore:
    """Append-only JSONL store of per-arm run counts (tamper-evident audit trail)."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append(self, rec: CampaignRecord) -> None:
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(rec.to_json() + "\n")

    def all(self) -> list[CampaignRecord]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as fh:
            return [CampaignRecord.from_json(line) for line in fh if line.strip()]

    def totals(self, campaign_id: str, arm: str) -> tuple[int, int]:
        """Accumulated (successes, n) for one arm across all recorded runs."""
        successes = n = 0
        for r in self.all():
            if r.campaign_id == campaign_id and r.arm == arm:
                successes += r.successes
                n += r.n
        return successes, n


def pass_counts(result: RunResult, score: str) -> tuple[int, int]:
    """(successes, n) for ``score`` over a run's items, matching pass_rate semantics:
    success = ``passed is True``; denominator = items where ``passed is not None``."""
    successes = n = 0
    for ir in result.items:
        for s in ir.scores:
            if s.name == score and s.passed is not None:
                n += 1
                if s.passed:
                    successes += 1
    return successes, n


def _run_arm(config: EvalConfig, arm: ModelSpec, *, langfuse_client: LangfuseClient | None) -> RunResult:
    from .engine import EvalEngine

    per_run = config.run.model_copy(update={"name": f"{config.run.name}::{arm.name}", "run_id": None})
    per_model = config.model_copy(
        update={"target": arm.target, "run": per_run, "comparison": None, "ab_campaign": None}
    )
    result: RunResult = EvalEngine.from_config(per_model, langfuse_client=langfuse_client).run()
    return result


def record_run(
    store: CampaignStore,
    config: EvalConfig,
    ab: ABCampaignConfig | None = None,
    *,
    langfuse_client: LangfuseClient | None = None,
    now: datetime | None = None,
) -> list[CampaignRecord]:
    """Run both arms once and append a per-arm count record. Returns the new records."""
    spec = ab if ab is not None else config.ab_campaign
    if spec is None:
        raise ValueError("record_run requires an ab_campaign config (config.ab_campaign or arg)")
    ts = (now or datetime.now(timezone.utc)).isoformat()
    records: list[CampaignRecord] = []
    for arm in (spec.arm_a, spec.arm_b):
        result = _run_arm(config, arm, langfuse_client=langfuse_client)
        successes, n = pass_counts(result, spec.score)
        rec = CampaignRecord(
            campaign_id=spec.campaign_id,
            arm=arm.name,
            score=spec.score,
            successes=successes,
            n=n,
            ts=ts,
        )
        store.append(rec)
        records.append(rec)
    return records


@dataclass
class ArmStats:
    arm: str
    successes: int
    n: int
    pass_rate: float | None
    ci_low: float
    ci_high: float


@dataclass
class CampaignResult:
    campaign_id: str
    score: str
    arm_a: ArmStats
    arm_b: ArmStats
    delta: float | None  # b.pass_rate - a.pass_rate
    decision: Decision
    min_sample: int

    def to_dict(self) -> dict:
        return {
            "campaign_id": self.campaign_id,
            "score": self.score,
            "decision": self.decision.value,
            "delta": self.delta,
            "min_sample": self.min_sample,
            "arms": {a.arm: _arm_dict(a) for a in (self.arm_a, self.arm_b)},
        }

    def to_html(self, title: str | None = None) -> str:
        return _render_html(self, title or f"A/B campaign: {self.campaign_id}")


def _arm_dict(a: ArmStats) -> dict:
    return {
        "successes": a.successes,
        "n": a.n,
        "pass_rate": a.pass_rate,
        "ci_low": a.ci_low,
        "ci_high": a.ci_high,
    }


def _arm_stats(store: CampaignStore, campaign_id: str, arm: str, score: str, z: float) -> ArmStats:
    from agent_core.calibration import wilson_interval

    successes, n = store.totals(campaign_id, arm)
    low, high = wilson_interval(successes, n, z)
    rate = (successes / n) if n else None
    return ArmStats(arm=arm, successes=successes, n=n, pass_rate=rate, ci_low=low, ci_high=high)


def analyze(
    store: CampaignStore,
    ab: ABCampaignConfig,
) -> CampaignResult:
    """Decide the campaign from accumulated counts using Wilson intervals.

    Powered & disjoint CIs -> a/b_better; powered & overlapping -> no_difference;
    either arm below ``min_sample`` -> cant_tell (no claim).
    """
    a = _arm_stats(store, ab.campaign_id, ab.arm_a.name, ab.score, ab.wilson_z)
    b = _arm_stats(store, ab.campaign_id, ab.arm_b.name, ab.score, ab.wilson_z)
    delta = (b.pass_rate - a.pass_rate) if (a.pass_rate is not None and b.pass_rate is not None) else None

    if a.n < ab.min_sample or b.n < ab.min_sample:
        decision = Decision.CANT_TELL
    elif b.ci_low > a.ci_high:
        decision = Decision.B_BETTER
    elif a.ci_low > b.ci_high:
        decision = Decision.A_BETTER
    else:
        decision = Decision.NO_DIFFERENCE

    return CampaignResult(
        campaign_id=ab.campaign_id,
        score=ab.score,
        arm_a=a,
        arm_b=b,
        delta=delta,
        decision=decision,
        min_sample=ab.min_sample,
    )


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def _render_html(result: CampaignResult, title: str) -> str:
    esc = _html.escape
    rows = []
    for a in (result.arm_a, result.arm_b):
        rows.append(
            f"<tr><td>{esc(a.arm)}</td><td>{a.successes}/{a.n}</td>"
            f"<td>{_fmt(a.pass_rate)}</td><td>[{_fmt(a.ci_low)}, {_fmt(a.ci_high)}]</td></tr>"
        )
    return "\n".join(
        [
            "<!DOCTYPE html>",
            '<html lang="en"><head><meta charset="utf-8">',
            f"<title>{esc(title)}</title>",
            "<style>body{font-family:system-ui,sans-serif;margin:2rem;}"
            "table{border-collapse:collapse;}th,td{border:1px solid #ccc;padding:.3rem .6rem;}</style>",
            "</head><body>",
            f"<h1>{esc(title)}</h1>",
            f"<p>score <code>{esc(result.score)}</code> — decision: "
            f"<strong>{esc(result.decision.value)}</strong> (delta={_fmt(result.delta)}, "
            f"min_sample={result.min_sample})</p>",
            "<table><tr><th>arm</th><th>passed/n</th><th>pass_rate</th><th>Wilson CI</th></tr>",
            *rows,
            "</table></body></html>",
        ]
    )
