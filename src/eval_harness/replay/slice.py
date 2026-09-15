"""Slice pass-rates from envelope tags so a global aggregate cannot hide a regression."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ..core.types import ItemResult, ScoreResult
from .envelope import ReplayConfig


@dataclass(frozen=True)
class SliceRow:
    tag_key: str
    tag_value: str
    n: int
    passed: int
    pass_rate: float | None


@dataclass(frozen=True)
class SliceDelta:
    tag_key: str
    tag_value: str
    baseline_pass_rate: float | None
    candidate_pass_rate: float | None
    delta: float | None


def _passed(scores: Sequence[ScoreResult], score_name: str) -> bool | None:
    for score in scores:
        if score.name == score_name:
            return score.passed
    return None


def tags_of(result: ItemResult) -> Mapping[str, str]:
    """Envelope tags copied onto ``item.metadata['replay_tags']`` by the replay CLI."""
    raw = result.item.metadata.get("replay_tags", {})
    if not isinstance(raw, Mapping):
        return {}
    return {str(k): str(v) for k, v in raw.items()}


def pass_rates_by_tag(
    results: Sequence[ItemResult],
    tag_key: str,
    *,
    score_name: str | None = None,
    config: ReplayConfig | None = None,
) -> tuple[SliceRow, ...]:
    """Group *results* by ``tags[tag_key]`` and compute pass-rate on *score_name*."""
    cfg = config or ReplayConfig()
    name = score_name if score_name is not None else cfg.slice_score
    buckets: dict[str, list[bool]] = {}
    for result in results:
        value = tags_of(result).get(tag_key, "")
        verdict = _passed(result.scores, name)
        if verdict is None:
            continue
        buckets.setdefault(value, []).append(verdict)
    rows: list[SliceRow] = []
    for tag_value, flags in sorted(buckets.items()):
        n = len(flags)
        passed = sum(1 for flag in flags if flag)
        rows.append(
            SliceRow(
                tag_key=tag_key,
                tag_value=tag_value,
                n=n,
                passed=passed,
                pass_rate=(passed / n) if n else None,
            )
        )
    return tuple(rows)


def global_pass_rate(
    results: Sequence[ItemResult],
    *,
    score_name: str | None = None,
    config: ReplayConfig | None = None,
) -> tuple[int, int, float | None]:
    """Return ``(passed, n, pass_rate)`` for *score_name* across all items."""
    cfg = config or ReplayConfig()
    name = score_name if score_name is not None else cfg.slice_score
    flags = [_passed(result.scores, name) for result in results]
    scored = [flag for flag in flags if flag is not None]
    n = len(scored)
    passed = sum(1 for flag in scored if flag)
    return passed, n, (passed / n) if n else None


def pass_rate_delta(
    baseline: Sequence[SliceRow],
    candidate: Sequence[SliceRow],
) -> tuple[SliceDelta, ...]:
    """Per-tag pass-rate change (candidate minus baseline)."""
    left = {(row.tag_key, row.tag_value): row for row in baseline}
    right = {(row.tag_key, row.tag_value): row for row in candidate}
    keys = sorted(set(left) | set(right))
    deltas: list[SliceDelta] = []
    for key in keys:
        b_row = left.get(key)
        c_row = right.get(key)
        b_rate = b_row.pass_rate if b_row is not None else None
        c_rate = c_row.pass_rate if c_row is not None else None
        delta = None if b_rate is None or c_rate is None else c_rate - b_rate
        deltas.append(
            SliceDelta(
                tag_key=key[0],
                tag_value=key[1],
                baseline_pass_rate=b_rate,
                candidate_pass_rate=c_rate,
                delta=delta,
            )
        )
    return tuple(deltas)
