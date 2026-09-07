"""Generation library for the synthetic RCA corpus (``scripts/gen_rca_corpus.py``).

Pure and deterministic: every choice flows from ``random.Random(seed)`` streams keyed by
item id, so a regeneration is byte-identical. Split from the CLI so the generator's tests
exercise the logic without shelling out (the ``_testgen_corpus_lib`` precedent).

**The telemetry is windowed, not timestamped.** Each metric carries ``pre`` and ``post``
arrays around the item's declared onset, so the ``max-|Z|`` baseline's pre/post contrast is
decidable without a clock. The confirmed cause's metrics step up at the onset; noise
controls how separable that step is, which is what makes the baseline's measured accuracy
a *property of the corpus* rather than a number imported from a leaderboard.

**Negative controls are shape-identical.** Unanswerable items (no candidate spikes) and
multi-cause items carry the same keys with the same shapes as single-cause items — the
spec forbids any target-visible field that marks them.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from typing import Any

#: Candidate service pool. Item candidate sets are drawn from these ids.
SERVICES: tuple[str, ...] = (
    "svc-api",
    "svc-auth",
    "svc-cart",
    "svc-pay",
    "db-primary",
    "db-replica",
    "cache-edge",
    "queue-main",
)

#: Metrics every candidate carries. The baseline z-scores each series independently.
METRICS: tuple[str, ...] = ("latency_ms", "error_rate", "cpu_util")

#: Timezones items declare. Varied so a timezone-insensitive comparison is measurably
#: wrong on a slice of the corpus (the spec's shifted-wall-clock scenario).
TIMEZONES: tuple[str, ...] = ("UTC", "UTC+08:00", "UTC-05:00")

#: Answerability classes. "hard-negative" items carry a spurious spike on a NON-cause
#: candidate (a confound the baseline must not over-credit); the class exists so the
#: corpus measures discrimination, not spike detection.
ITEM_CLASSES: tuple[str, ...] = ("single", "unanswerable", "multi", "hard-negative")

#: Difficulty strata as (noise, signal_z) pairs: noise is the per-sample jitter (relative
#: to the series base) and signal_z is the z-score the true cause's step presents against
#: the pre-window spread. Difficulty lives in the z-band, not the absolute step: the
#: baseline's measured accuracy per stratum is what the manifest records and the
#: generator's calibrated bands gate on. Calibrated 2026-09-06 against
#: RcaMaxZBaselineTarget's default floor: s0 solves, s1 is partial, s2 is declined.
STRATA: tuple[tuple[float, float], ...] = (
    (0.05, 5.0),  # easy: the baseline should mostly succeed
    (0.15, 2.0),  # mid: the baseline should be partial
    (0.30, 1.0),  # hard: the baseline should mostly decline
)

#: The confound spike on a hard-negative is slightly stronger than the true cause's, so
#: the baseline's top-1 is the confound unless it discounts the stronger-but-wrong signal.
CONFOUND_Z_FACTOR = 1.15

#: Samples per window (pre / post) per metric.
WINDOW = 24


@dataclass(frozen=True)
class ItemSpec:
    """The deterministic inputs to one corpus item."""

    item_id: str
    item_class: str  # one of ITEM_CLASSES
    stratum: str  # e.g. "s0" — the difficulty stratum label
    noise: float
    signal_z: float
    timezone: str


def bucket(seed: int, key: str) -> float:
    """``flow_corpus.partition``'s keyed-holdout idiom, reused as an idiom (F-011 airgap).

    sha256 over ``"{seed}:{key}"`` folded into [0, 1): the split is a pure function of the
    item id, so iterating on scorers never reshuffles which items are sequestered.
    """
    digest = hashlib.sha256(f"{seed}:{key}".encode()).hexdigest()
    return int(digest[:8], 16) / 0x100000000


def _series(rng: random.Random, base: float, step: float, noise: float) -> dict[str, list[float]]:
    """One metric's pre/post windows: flat at ``base``, stepping by ``step`` at onset."""
    jitter_pre = [base + rng.gauss(0.0, noise * max(base, 1.0)) for _ in range(WINDOW)]
    jitter_post = [base + step + rng.gauss(0.0, noise * max(base, 1.0)) for _ in range(WINDOW)]
    return {"pre": [round(v, 4) for v in jitter_pre], "post": [round(v, 4) for v in jitter_post]}


def build_item(spec: ItemSpec, seed: int) -> dict[str, Any]:
    """One corpus item, fully determined by ``(spec, seed)``."""
    rng = random.Random(f"{seed}:{spec.item_id}")
    candidates = list(rng.sample(SERVICES, k=4))
    base_onset_day = 1 + rng.randrange(28)
    onset = f"2026-03-{base_onset_day:02d}T{rng.randrange(24):02d}:{rng.randrange(60):02d}:00{_offset(spec.timezone)}"

    if spec.item_class == "unanswerable":
        correct: list[str] = []
        spiking: list[str] = []
        confound: list[str] = []
    elif spec.item_class == "multi":
        correct = candidates[:2]
        spiking = list(correct)
        confound = []
    elif spec.item_class == "hard-negative":
        correct = candidates[:1]
        spiking = [correct[0], candidates[2]]  # a non-cause spikes too
        confound = [candidates[2]]
    else:  # single
        correct = candidates[:1]
        spiking = list(correct)
        confound = []

    metrics: dict[str, dict[str, dict[str, list[float]]]] = {}
    for svc in candidates:
        per_metric = {}
        # A fault moves one or two metrics, never all three: a cause that spiked every
        # metric would win every ranking by construction (three consistent signals beat
        # the noise max), and the corpus would measure spike-counting, not diagnosis.
        spiking_metrics = set(rng.sample(list(METRICS), k=rng.choice((1, 1, 2)))) if svc in spiking else set()
        for metric in METRICS:
            base = float(rng.randrange(50, 200))
            if metric in spiking_metrics:
                # The step is sized in z units: signal_z * the pre-window's own spread.
                # Difficulty lives in the z-band, so the stratum — not the absolute
                # spike size — is what separates an easy item from a hard one.
                z = spec.signal_z * (CONFOUND_Z_FACTOR if svc in confound else 1.0)
                step = z * spec.noise * max(base, 1.0)
                per_metric[metric] = _series(rng, base, step, spec.noise)
            else:
                per_metric[metric] = _series(rng, base, 0.0, spec.noise)
        metrics[svc] = per_metric

    events = [
        f"{onset} deploy finished for {spiking[0]}" if spiking else f"{onset} nightly batch completed",
        f"{onset} alert: elevated {METRICS[0]} on {spiking[-1]}" if spiking else f"{onset} heartbeat ok",
    ]
    return {
        "instance_id": spec.item_id,
        "item_class": spec.item_class,
        "stratum": spec.stratum,
        "timezone": spec.timezone,
        "candidates": candidates,
        "correct": correct,
        "onset": onset,
        "telemetry": {"metrics": metrics, "events": events},
        "difficulty": round(1.0 - spec.signal_z / max(z for _, z in STRATA), 4),
        "noise": spec.noise,
    }


def _offset(timezone: str) -> str:
    """The ISO-8601 offset suffix for a declared timezone label."""
    return {"UTC": "+00:00", "UTC+08:00": "+08:00", "UTC-05:00": "-05:00"}[timezone]


def item_hash(item: dict[str, Any]) -> str:
    """Content hash over an item, so a hand-edited corpus fails ``--check``."""
    return hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()


def validate_item(item: dict[str, Any]) -> list[str]:
    """Load-time rejection rules (spec: candidate set and timezone are mandatory).

    Returns the list of problems (empty = valid). An item with no candidate set, or with
    timestamps and no declared timezone, is rejected — never silently scored against a
    singleton set or compared in an implicit local zone.
    """
    problems: list[str] = []
    candidates = item.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        problems.append(f"{item.get('instance_id', '?')}: missing or empty 'candidates'")
    if not isinstance(item.get("timezone"), str) or not item["timezone"]:
        problems.append(f"{item.get('instance_id', '?')}: missing 'timezone' declaration")
    elif item["timezone"] not in TIMEZONES:
        problems.append(f"{item.get('instance_id', '?')}: undeclared timezone {item['timezone']!r}")
    correct = item.get("correct")
    if not isinstance(correct, list):
        problems.append(f"{item.get('instance_id', '?')}: 'correct' must be a list (possibly empty)")
    elif isinstance(candidates, list) and any(c not in candidates for c in correct):
        problems.append(f"{item.get('instance_id', '?')}: a confirmed cause is outside the candidate set")
    return problems
