#!/usr/bin/env python3
"""Validation script for F-047 — proxy-correlation measurement, PPI++ estimator, propensity.

Deterministic and offline: reads module / workflow TEXT only (no ``agent_core`` import,
which the validation gate does not install). Pins the invariants that make the new
reporting honest, so a future edit cannot silently regress them.

    1. The GATE is untouched: merge_gate.decide() still calls wilson_interval, and neither
       merge_gate nor merge_gate_ci imports the estimator or either report module -- no new
       code path can reach an auto-merge decision.
    2. Wilson remains the report DEFAULT; ``ppi++`` is opt-in.
    3. PPI++ is fail-closed: every guarded path returns the Wilson interval, and the
       degenerate reasons that make small-n honest are present (min_labeled floor, single
       outcome class, constant proxy, out-of-range proxy, no residual dof).
    4. ``variance_reduction`` is derived from the standard errors, NOT from the clipped
       bounds -- the bug that reported a 3% gain as 94%.
    5. Degenerate slices withhold AUROC rather than printing the by-construction 0.5.
    6. selection_propensity has a real producer and consumer (the audit workflow selects
       ``--with-propensity``; the verdict recorder threads it) and is nullable so older
       records still load.

Exit codes: 0 all checks passed; 1 one or more failed.
"""

from __future__ import annotations

import logging
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.dirname(_HERE)
for _p in (_HERE, _SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _common import check as _check
from _common import configure_logging, report

logger = logging.getLogger(__name__)

_ROOT = os.path.dirname(_SCRIPTS)
_AC = os.path.join("agent-core", "agent_core")


def _read(*parts: str) -> str:
    with open(os.path.join(_ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def validate_f047() -> int:
    configure_logging()
    errors: list[str] = []

    ppi = _read(_AC, "ppi.py")
    proxy_eval = _read(_AC, "proxy_eval.py")
    report_types = _read(_AC, "report_types.py")
    render = _read(_AC, "calibration_report_render.py")
    gate = _read(_AC, "merge_gate.py")
    gate_ci = _read(_AC, "merge_gate_ci.py")
    sampler = _read(_AC, "audit_sampler.py")
    store = _read(_AC, "outcome_store.py")
    audit_wf = _read(".github", "workflows", "merge-gate-audit.yml")
    verdict_wf = _read(".github", "workflows", "merge-gate-verdict.yml")
    recorder = _read("scripts", "record_audit_verdict.py")
    issue_sync = _read("scripts", "audit_issue_sync.py")

    # 1. The gate is untouched and unreachable from the new reporting modules.
    _check("wilson_interval(" in gate, "merge_gate still computes the Wilson bound", errors)
    for name, src in (("merge_gate", gate), ("merge_gate_ci", gate_ci)):
        for banned in ("ppi", "proxy_eval", "calibration_report"):
            _check(
                f"from .{banned} import" not in src and f"import {banned}" not in src,
                f"{name} does not import {banned} (no new path to a gate decision)",
                errors,
            )

    # 2. Wilson is the default; ppi++ is opt-in.
    _check('WILSON = "wilson"' in report_types, "wilson is single-sourced", errors)
    _check('estimator: str = "wilson"' in report_types, "report defaults to wilson", errors)
    _check('PPI_PLUS = "ppi++"' in report_types, "ppi++ is a named opt-in estimator", errors)

    # 3. Fail-closed degeneracy: every guarded path falls back to Wilson, with a reason.
    _check("fallback_lo, fallback_hi = wilson_interval(" in ppi, "PPI falls back to Wilson", errors)
    for reason in (
        "insufficient labelled samples",
        "single outcome class",
        "constant proxy",
        "proxy outside",
        "no residual degrees of freedom",
    ):
        _check(reason in ppi, f"PPI degenerate reason present: {reason!r}", errors)
    _check(
        "ppi.min_labeled must be >= 3" in ppi,
        "min_labeled floor >= 3 (a tuned lambda needs residual degrees of freedom)",
        errors,
    )

    # 4. variance_reduction comes from the standard errors, not the clipped bounds.
    _check(
        "ratio = self.se / self.se_classical" in ppi,
        "variance_reduction is derived from the standard errors, not clipped widths",
        errors,
    )
    _check(
        "def variance_reduction(self) -> float | None:" in ppi,
        "variance_reduction is None when no trustworthy comparison exists",
        errors,
    )

    # 5. A degenerate slice withholds AUROC (never the by-construction 0.5).
    _check(
        "if degenerate is None and len({int(y) for y in ys}) == 2:" in proxy_eval,
        "proxy_eval withholds AUROC on a degenerate slice",
        errors,
    )
    _check(
        "classical (λ=0)" in render,
        "the report renders the classical baseline the reduction is measured against",
        errors,
    )

    # 6. selection_propensity has a producer, a carrier and a consumer, and is nullable.
    _check(
        "selection_propensity: float | None = None" in store,
        "OutcomeRecord.selection_propensity is nullable (older records still load)",
        errors,
    )
    _check("--with-propensity" in audit_wf, "audit workflow selects with propensity", errors)
    _check(
        "selection_propensity:" in verdict_wf and "PROPENSITY:" in verdict_wf,
        "verdict workflow accepts the propensity and routes it through env",
        errors,
    )
    _check(
        "--selection-propensity" in recorder and "selection_propensity=selection_propensity" in recorder,
        "the verdict recorder threads the propensity to record_verdict",
        errors,
    )
    _check(
        "def inclusion_probability(" in sampler,
        "the sampler computes a marginal inclusion probability",
        errors,
    )

    # 7. The propensity contract is single-sourced, and every layer defers to it.
    _check(
        "def is_valid_propensity(" in sampler and "def format_propensity(" in sampler,
        "the propensity contract (validity + rendering) is defined once, in agent_core",
        errors,
    )
    _check(
        "if not is_valid_propensity(selection_propensity):" in sampler,
        "the store write boundary validates through the shared predicate",
        errors,
    )
    for name, src in (("audit_issue_sync", issue_sync), ("record_audit_verdict", recorder)):
        _check(
            "is_valid_propensity" in src,
            f"{name} screens propensities through the shared predicate, not a restated comparison",
            errors,
        )
        _check(
            "0.0 < " not in src,
            f"{name} does not restate the range check (it would drift from the contract)",
            errors,
        )

    # 8. The verdict workflow cannot be argument-injected through the dispatch input.
    #    An unquoted scalar word-splits, so `0.5 --store /tmp/x` would append a second
    #    --store that argparse resolves last-wins. Only an array expansion prevents it.
    _check(
        "PROP_ARGS=()" in verdict_wf and '"${PROP_ARGS[@]}"' in verdict_wf,
        "the verdict workflow builds the optional flag as a quoted array (no word-split)",
        errors,
    )
    _check(
        "$PROP_ARGS" not in verdict_wf.replace('"${PROP_ARGS[@]}"', ""),
        "the verdict workflow never expands the propensity args unquoted",
        errors,
    )

    return report(logger, "F-047", errors)


def main() -> int:
    return validate_f047()


if __name__ == "__main__":
    sys.exit(main())
