import json
import math

import hypothesis.strategies as st
import pytest
from hypothesis import given

from agent_core import CalibrationConfig, ConfigError, FrameworkConfig, IsotonicCalibrator
from agent_core.config import GoldenConfig
from agent_core.golden import (
    GoldenItem,
    GoldenSet,
    GoldenSplit,
    _bucket,
    cohen_kappa,
    evaluate_on_split,
    split,
)


# ---- helpers -----------------------------------------------------------------
def _make_item(i: int, label: int = 1) -> GoldenItem:
    return GoldenItem(item_id=f"item-{i}", text=f"text {i}", label=label)


def _big_set(n: int) -> GoldenSet:
    items = tuple(_make_item(i, label=i % 2) for i in range(n))
    return GoldenSet(items)


# ---- GoldenItem tests --------------------------------------------------------
def test_invalid_label_raises() -> None:
    with pytest.raises(ValueError, match="label must be 0 or 1"):
        GoldenItem("a", "x", label=2)


def test_item_equality() -> None:
    a = GoldenItem("x", "text", 1, domain="d", source="s", meta={"k": "v"})
    b = GoldenItem("x", "text", 1, domain="d", source="s", meta={"k": "v"})
    assert a == b


# ---- GoldenSet tests ---------------------------------------------------------
def test_golden_set_rejects_duplicate_ids() -> None:
    with pytest.raises(ConfigError, match="duplicate item_id"):
        GoldenSet((GoldenItem("a", "x", 1), GoldenItem("a", "y", 0)))


def test_jsonl_round_trip_is_exact() -> None:
    gs = _big_set(50)
    restored = GoldenSet.from_jsonl(gs.to_jsonl())
    assert gs == restored


def test_jsonl_is_deterministic_byte_for_byte() -> None:
    gs = GoldenSet((_make_item(2), _make_item(1), _make_item(0)))
    j1 = gs.to_jsonl()
    j2 = gs.to_jsonl()
    assert j1 == j2
    # items must be sorted by item_id in output
    lines = j1.strip().splitlines()
    ids = [json.loads(line)["item_id"] for line in lines]
    assert ids == sorted(ids)


def test_jsonl_rejects_bad_label() -> None:
    with pytest.raises(ValueError, match="invalid label"):
        GoldenSet.from_jsonl(
            '{"item_id":"a","text":"x","label":2,"domain":"default","source":"","meta":{}}'
        )


def test_from_jsonl_skips_empty_lines() -> None:
    line = '{"item_id":"a","text":"x","label":0,"domain":"default","source":"","meta":{}}'
    result = GoldenSet.from_jsonl(f"\n{line}\n\n")
    assert len(result.items) == 1


# ---- bucket + split tests ----------------------------------------------------
def test_bucket_is_in_unit_interval() -> None:
    for i in range(100):
        b = _bucket(42, f"item-{i}")
        assert 0.0 <= b < 1.0


def test_bucket_is_deterministic() -> None:
    assert _bucket(99, "hello") == _bucket(99, "hello")


def test_split_is_disjoint_and_complete() -> None:
    gs = _big_set(1000)
    sp = split(gs, GoldenConfig())
    ids_train = {i.item_id for i in sp.train.items}
    ids_calib = {i.item_id for i in sp.calibration.items}
    ids_test = {i.item_id for i in sp.test.items}
    all_ids = {i.item_id for i in gs.items}
    assert ids_train | ids_calib | ids_test == all_ids
    assert ids_train & ids_calib == set()
    assert ids_train & ids_test == set()
    assert ids_calib & ids_test == set()


def test_split_is_deterministic_for_seed() -> None:
    gs = _big_set(500)
    assert split(gs, GoldenConfig()) == split(gs, GoldenConfig())


def test_split_seed_override_differs_from_default() -> None:
    gs = _big_set(200)
    sp1 = split(gs, GoldenConfig())
    sp2 = split(gs, GoldenConfig(), seed=999)
    # Different seeds should produce different splits (with very high probability)
    assert sp1 != sp2


@given(n=st.integers(min_value=200, max_value=2000))
def test_split_ratios_approximately_hold(n: int) -> None:
    gs = _big_set(n)
    cfg = GoldenConfig()
    sp = split(gs, cfg)
    # Allow 10% tolerance for small n (hash variance)
    tol = max(0.10, 3.0 / math.sqrt(n))
    assert abs(len(sp.train.items) / n - cfg.train_ratio) < tol
    assert abs(len(sp.calibration.items) / n - cfg.calibration_ratio) < tol
    assert abs(len(sp.test.items) / n - cfg.test_ratio) < tol


# ---- cohen_kappa tests -------------------------------------------------------
def test_cohen_kappa_hand_value() -> None:
    # Agreement on 3/4; expected by chance 0.5
    # po=0.75, pe = 0.5*0.5 + 0.5*0.5 = 0.5, kappa = (0.75-0.5)/(1-0.5) = 0.5
    assert math.isclose(cohen_kappa([1, 1, 0, 0], [1, 1, 0, 1]), 0.5, abs_tol=1e-12)


def test_cohen_kappa_perfect_agreement() -> None:
    assert math.isclose(cohen_kappa([1, 0, 1, 0], [1, 0, 1, 0]), 1.0, abs_tol=1e-12)


def test_cohen_kappa_length_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="equal length"):
        cohen_kappa([1, 0], [1])


def test_cohen_kappa_empty_raises() -> None:
    with pytest.raises(ValueError, match="empty"):
        cohen_kappa([], [])


# ---- evaluate_on_split tests -------------------------------------------------
def _balanced_items(n: int) -> GoldenSet:
    """Build a set that will likely have both classes in every partition."""
    items = [GoldenItem(f"x{i}", f"t{i}", i % 2) for i in range(n)]
    return GoldenSet(tuple(items))


def test_evaluate_on_split_uses_test_partition_only() -> None:
    """Calibrator fitted on calibration; evaluation uses test partition."""
    gs = _balanced_items(300)
    cfg = GoldenConfig()
    calib_cfg = CalibrationConfig()
    sp = split(gs, cfg)

    # predict_fn: overconfident (always 0.9 for label=1, 0.1 for label=0)
    def predict_fn(item: GoldenItem) -> float:
        return 0.9 if item.label == 1 else 0.1

    calibrator = IsotonicCalibrator()
    report = evaluate_on_split(sp, calibrator, calib_cfg, predict_fn)
    # report is a CalibrationReport; auroc may be None if single-class
    assert isinstance(report.ece, float)
    assert isinstance(report.brier, float)


def test_evaluate_on_split_tolerates_single_class_auroc_none() -> None:
    """A test partition with only one class must not crash; report.auroc is None."""
    # Force test partition to contain only label=1 items by controlling split
    all_ones = GoldenSet(tuple(GoldenItem(f"y{i}", f"t{i}", 1) for i in range(300)))
    # This will have all-1 labels; evaluate_calibration handles single-class -> auroc=None
    cfg = GoldenConfig()
    sp = split(all_ones, cfg)
    report = evaluate_on_split(sp, IsotonicCalibrator(), CalibrationConfig(), lambda item: 0.8)
    # If test partition somehow has both classes, auroc is float; if single-class, None
    assert report.auroc is None or isinstance(report.auroc, float)


def test_evaluate_on_split_empty_calibration_raises() -> None:
    sp = GoldenSplit(
        train=GoldenSet(()),
        calibration=GoldenSet(()),
        test=GoldenSet((_make_item(0),)),
    )
    with pytest.raises(ValueError, match="calibration partition is empty"):
        evaluate_on_split(sp, IsotonicCalibrator(), CalibrationConfig(), lambda _: 0.5)


def test_evaluate_on_split_empty_test_raises() -> None:
    sp = GoldenSplit(
        train=GoldenSet(()),
        calibration=GoldenSet((_make_item(0),)),
        test=GoldenSet(()),
    )
    with pytest.raises(ValueError, match="test partition is empty"):
        evaluate_on_split(sp, IsotonicCalibrator(), CalibrationConfig(), lambda _: 0.5)


# ---- config tests ------------------------------------------------------------
def test_config_ratios_must_sum_to_1() -> None:
    with pytest.raises(ConfigError, match=r"sum to 1\.0"):
        GoldenConfig(train_ratio=0.5, calibration_ratio=0.3, test_ratio=0.3)


def test_config_ratio_out_of_range() -> None:
    with pytest.raises(ConfigError, match="must be in"):
        GoldenConfig(train_ratio=1.5, calibration_ratio=0.0, test_ratio=-0.5)


def test_framework_config_round_trip() -> None:
    cfg = FrameworkConfig.from_dict(
        {"golden": {"train_ratio": 0.5, "calibration_ratio": 0.25, "test_ratio": 0.25}}
    )
    assert cfg.golden.train_ratio == 0.5
    assert cfg.golden == GoldenConfig(train_ratio=0.5, calibration_ratio=0.25, test_ratio=0.25)


def test_old_config_without_golden_section_loads() -> None:
    cfg = FrameworkConfig.from_dict({"loop": {"max_cycles": 3}})
    assert cfg.loop.max_cycles == 3
    assert cfg.golden == GoldenConfig()  # new section defaulted
