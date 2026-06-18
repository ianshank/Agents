"""Golden-set construction and evaluation tooling.

Deterministic, reproducible dataset partitioning for calibration experiments.
Splits are assigned by hash (seed:item_id) so they are stable across runs and
independent of insertion order. evaluate_on_split enforces held-out discipline
in code: calibrator is fit on the calibration partition, evaluated on test only.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field

from .calibration import CalibrationReport, Calibrator, evaluate_calibration
from .config import CalibrationConfig, ConfigError, GoldenConfig
from .logging_util import debug_span, get_logger

_log = get_logger("agent_core.golden")


@dataclass(frozen=True)
class GoldenItem:
    item_id: str
    text: str
    label: int  # 0 or 1 only
    domain: str = "default"
    source: str = ""
    meta: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.label not in (0, 1):
            raise ValueError(f"GoldenItem.label must be 0 or 1, got {self.label!r}")

    def __hash__(self) -> int:
        # meta dict is unhashable; hash on stable fields only
        return hash((self.item_id, self.text, self.label, self.domain, self.source))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, GoldenItem):
            return NotImplemented
        return (
            self.item_id == other.item_id
            and self.text == other.text
            and self.label == other.label
            and self.domain == other.domain
            and self.source == other.source
            and self.meta == other.meta
        )


@dataclass(frozen=True, eq=False)
class GoldenSet:
    items: tuple[GoldenItem, ...]

    def __post_init__(self) -> None:
        # reject duplicate item_ids — silent ratio skew risk
        seen: set[str] = set()
        for item in self.items:
            if item.item_id in seen:
                raise ConfigError(f"duplicate item_id in GoldenSet: {item.item_id!r}")
            seen.add(item.item_id)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, GoldenSet):
            return NotImplemented
        # order-independent: GoldenSet is a set of items, not an ordered sequence
        return frozenset(self.items) == frozenset(other.items)

    def __hash__(self) -> int:
        return hash(frozenset(self.items))

    def to_jsonl(self) -> str:
        """Deterministic JSONL: rows sorted by item_id, each row sort_keys=True."""
        rows = sorted(self.items, key=lambda x: x.item_id)
        lines = [json.dumps(asdict(item), sort_keys=True) for item in rows]
        return "\n".join(lines) + "\n"

    @classmethod
    def from_jsonl(cls, text: str) -> GoldenSet:
        items: list[GoldenItem] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            label = d.get("label")
            if label not in (0, 1):
                raise ValueError(f"invalid label in JSONL: {label!r}")
            items.append(
                GoldenItem(
                    item_id=str(d["item_id"]),
                    text=str(d["text"]),
                    label=int(d["label"]),
                    domain=str(d.get("domain", "default")),
                    source=str(d.get("source", "")),
                    meta={str(k): str(v) for k, v in d.get("meta", {}).items()},
                )
            )
        return cls(tuple(items))


@dataclass(frozen=True)
class GoldenSplit:
    train: GoldenSet
    calibration: GoldenSet
    test: GoldenSet


def _bucket(seed: int, item_id: str) -> float:
    """Deterministic, order-independent hash bucket in [0, 1)."""
    h = hashlib.sha256(f"{seed}:{item_id}".encode()).hexdigest()
    return int(h[:16], 16) / float(1 << 64)


def split(gs: GoldenSet, config: GoldenConfig, seed: int | None = None) -> GoldenSplit:
    """Assign each item deterministically to train/calibration/test by hash bucket."""
    effective_seed = seed if seed is not None else config.split_seed
    train_items: list[GoldenItem] = []
    calib_items: list[GoldenItem] = []
    test_items: list[GoldenItem] = []

    train_edge = config.train_ratio
    calib_edge = config.train_ratio + config.calibration_ratio

    for item in gs.items:
        b = _bucket(effective_seed, item.item_id)
        if b < train_edge:
            train_items.append(item)
        elif b < calib_edge:
            calib_items.append(item)
        else:
            test_items.append(item)

    return GoldenSplit(
        train=GoldenSet(tuple(train_items)),
        calibration=GoldenSet(tuple(calib_items)),
        test=GoldenSet(tuple(test_items)),
    )


def cohen_kappa(r1: Sequence[int], r2: Sequence[int]) -> float:
    """Cohen's kappa for label agreement between two annotators."""
    if len(r1) != len(r2):
        raise ValueError("cohen_kappa: sequences must have equal length")
    n = len(r1)
    if n == 0:
        raise ValueError("cohen_kappa: empty sequences")
    categories = sorted(set(r1) | set(r2))
    agree = sum(a == b for a, b in zip(r1, r2, strict=False))
    po = agree / n
    # expected agreement across all observed categories (not hardcoded to (0, 1))
    freq1 = [sum(1 for x in r1 if x == c) / n for c in categories]
    freq2 = [sum(1 for x in r2 if x == c) / n for c in categories]
    pe = sum(f1 * f2 for f1, f2 in zip(freq1, freq2, strict=False))
    if math.isclose(pe, 1.0):
        return 1.0
    return (po - pe) / (1.0 - pe)


def evaluate_on_split(
    sp: GoldenSplit,
    calibrator: Calibrator,
    calib_config: CalibrationConfig,
    predict_fn: Callable[[GoldenItem], float],
) -> CalibrationReport:
    """Fit calibrator on calibration partition; evaluate on TEST only.

    Enforces held-out discipline in code. report.auroc may be None if the
    test slice is single-class (hash split has no class-balance guarantee).
    """
    if not sp.calibration.items:
        raise ValueError("calibration partition is empty; cannot fit")
    if not sp.test.items:
        raise ValueError("test partition is empty; cannot evaluate")

    with debug_span(_log, "evaluate_on_split.fit", calib_n=len(sp.calibration.items)):
        calib_probs = [predict_fn(item) for item in sp.calibration.items]
        calib_labels = [item.label for item in sp.calibration.items]
        calibrator.fit(calib_probs, calib_labels)

    with debug_span(_log, "evaluate_on_split.evaluate", test_n=len(sp.test.items)):
        test_probs = [calibrator.predict(predict_fn(item)) for item in sp.test.items]
        test_labels = [item.label for item in sp.test.items]

    return evaluate_calibration(
        test_probs,
        test_labels,
        n_bins=calib_config.n_bins,
        ece_target=calib_config.ece_target,
        mce_target=calib_config.mce_target,
        auroc_target=calib_config.auroc_target,
    )
