"""Optional Streamlit shell over a :class:`RegressionReport`.

This is a thin presentation layer, never a source of truth — it renders the same
deterministic report the gate consumes. ``streamlit`` is imported lazily behind the
``[dashboard]`` extra so the offline/test path never depends on it. Run with::

    streamlit run behavioral-regression/behavioral_regression/dashboard.py
"""

from __future__ import annotations

import json

from .config import BRConfig
from .pipeline import run_pipeline
from .report import RegressionReport


def render(report: RegressionReport) -> None:  # pragma: no cover - requires streamlit
    """Render a report into the active Streamlit page."""
    try:
        import streamlit as st
    except ImportError as exc:
        raise RuntimeError(
            "dashboard requires streamlit. Install with: "
            "pip install 'behavioral-regression[dashboard]'"
        ) from exc

    payload = report.to_dict()
    st.title("Behavioural Regression — did v2 drift?")
    st.subheader(f"Gate decision: {report.decision.value.upper()}")
    st.components.v1.html(report.to_html(), height=260)
    st.json(payload)


def _main() -> None:  # pragma: no cover - requires streamlit
    import streamlit as st

    seed = int(st.sidebar.number_input("seed", value=7, step=1))
    v2_mean = float(
        st.sidebar.slider("v2 sycophancy mean", 0.0, 1.0, BRConfig().v2_sycophancy_mean)
    )
    cfg = BRConfig(v2_sycophancy_mean=v2_mean)
    report = run_pipeline(cfg, seed=seed)
    render(report)
    st.download_button(
        "Download report.json",
        json.dumps(report.to_dict(), sort_keys=True, indent=2),
        file_name="report.json",
    )


if __name__ == "__main__":  # pragma: no cover
    _main()
