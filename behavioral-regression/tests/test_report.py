from __future__ import annotations

import json
import math

from behavioral_regression.config import BRConfig  # type: ignore[import-not-found]
from behavioral_regression.pipeline import run_pipeline  # type: ignore[import-not-found]
from behavioral_regression.report import _num  # type: ignore[import-not-found]


def test_num_normalises_non_finite():
    assert _num(None) is None
    assert _num(float("nan")) is None
    assert _num(float("inf")) is None
    assert _num(0.25) == 0.25


def test_to_dict_is_json_serialisable_and_keyed():
    report = run_pipeline(BRConfig(n_pairs=200), seed=7)
    d = report.to_dict()
    text = json.dumps(d, sort_keys=True)  # must not raise (no NaN/inf leak)
    assert "decision" in d
    assert set(d["estimate"]) >= {"p_regression", "delta_excludes_zero", "cant_tell"}
    assert isinstance(d["reliability_bins"], list)
    # round-trips deterministically
    assert json.loads(text)["decision"] == d["decision"]


def test_empty_bins_serialise_without_nan():
    # A huge indeterminate band ⇒ every verdict abstains ⇒ no labelled bins.
    cfg = BRConfig(n_pairs=120, judge_indeterminate_band=0.99)
    report = run_pipeline(cfg, seed=1)
    assert report.bins == []
    json.dumps(report.to_dict())  # must not raise


def test_to_html_has_badge_and_svg():
    report = run_pipeline(BRConfig(n_pairs=150, v2_sycophancy_mean=0.45), seed=3)
    html = report.to_html()
    assert "<svg" in html
    assert report.decision.value.upper() in html
    assert not math.isnan(0.0)  # sanity
