"""The run report: a deterministic, JSON-serialisable record + a self-contained HTML
reliability diagram. This is the tested source of truth the gate and the (optional)
Streamlit shell both consume.

``to_dict`` is byte-stable (NaNs from empty reliability bins are normalised to ``None``)
so the same ``(BRConfig, seed)`` round-trips identically — the determinism guarantee.
``to_html`` emits a dependency-free inline-SVG reliability diagram plus a decision badge.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from agent_core.calibration import Bin
from flow_corpus.oracles.kappa_gate import KappaReport

from .canary import CanaryReport
from .detector import RegressionEstimate
from .gate import ShipDecision

_BADGE_COLOURS = {
    ShipDecision.SHIP: "#1a7f37",
    ShipDecision.HOLD: "#bf8700",
    ShipDecision.ESCALATE: "#cf222e",
}


def _num(x: float | None) -> float | None:
    """JSON-safe number: NaN/inf (empty-bin sentinels) become ``None``."""
    if x is None or math.isnan(x) or math.isinf(x):
        return None
    return x


def _bin_to_dict(b: Bin) -> dict[str, Any]:
    return {
        "lo": b.lo,
        "hi": b.hi,
        "count": b.count,
        "mean_conf": _num(b.mean_conf),
        "accuracy": _num(b.accuracy),
        "ci_low": b.ci_low,
        "ci_high": b.ci_high,
    }


@dataclass(frozen=True)
class RegressionReport:
    estimate: RegressionEstimate
    kappa: KappaReport
    canary: CanaryReport
    decision: ShipDecision
    bins: Sequence[Bin]

    def to_dict(self) -> dict[str, Any]:
        est = self.estimate
        return {
            "decision": self.decision.value,
            "estimate": {
                "p_regression": est.p_regression,
                "wilson_low": est.wilson_low,
                "wilson_high": est.wilson_high,
                "delta_point": est.delta_ci.point,
                "delta_low": est.delta_ci.low,
                "delta_high": est.delta_ci.high,
                "delta_excludes_zero": est.delta_ci.excludes_zero,
                "brier": _num(est.brier),
                "reliability": _num(est.reliability),
                "n_determinate": est.n_determinate,
                "cant_tell": est.cant_tell,
            },
            "oracle": {
                "kappa": _num(self.kappa.kappa),
                "n_codeterminate": self.kappa.n_codeterminate,
                "directional_only": self.kappa.directional_only,
                "may_gate": self.kappa.may_gate,
            },
            "canary": {
                "regressed_p": self.canary.regressed_p,
                "null_p": self.canary.null_p,
                "margin": self.canary.margin,
                "separated": self.canary.separated,
            },
            "reliability_bins": [_bin_to_dict(b) for b in self.bins],
        }

    def to_html(self) -> str:
        """A self-contained HTML fragment: a decision badge + an SVG reliability diagram."""
        colour = _BADGE_COLOURS[self.decision]
        badge = (
            f'<div style="display:inline-block;padding:6px 14px;border-radius:6px;'
            f'background:{colour};color:#fff;font-weight:700;font-family:sans-serif">'
            f"{self.decision.value.upper()}</div>"
        )
        rows = []
        for b in self.bins:
            if not b.is_populated:
                continue
            x = b.mean_conf * 280
            y = (1.0 - b.accuracy) * 200
            rows.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{colour}"></circle>')
        diagonal = '<line x1="0" y1="200" x2="280" y2="0" stroke="#888" stroke-dasharray="4"/>'
        svg = (
            '<svg width="300" height="220" viewBox="0 0 300 220" '
            'xmlns="http://www.w3.org/2000/svg">'
            f'<rect width="300" height="220" fill="#fafafa"/>{diagonal}'
            f"{''.join(rows)}"
            '<text x="6" y="214" font-size="10" font-family="sans-serif">reliability '
            "(x: confidence, y: accuracy)</text></svg>"
        )
        return f"<div>{badge}<br/>{svg}</div>"
