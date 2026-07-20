"""The synthetic negative control: probe a deliberately unroutable endpoint (spec R5).

If this reports ``ok`` the probe layer itself cannot be trusted — the phase runner HALTs.
"""

from __future__ import annotations

from backend_validation.registry import register
from backend_validation.runner import ProbeRun


@register("control.synthetic.unreachable")
def synthetic_unreachable(run: ProbeRun) -> None:
    record = run.op("probe_endpoint", {"url": run.ctx.control_endpoint})
    record.note(control_target=run.ctx.control_endpoint)
