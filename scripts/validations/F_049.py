#!/usr/bin/env python3
"""Validation script for F-049 — merge-gate calibrator-health integrity.

Deterministic and offline: reads module TEXT only (no ``agent_core`` import, which the
validation gate does not install). Pins the invariants that make the gate's fourth health
floor actually do work, so a future edit cannot silently reinstate the fail-open.

    1. The bin-CI floor cannot pass unmeasured. ``_operating_bin_ci_width`` is declared
       ``-> float | None``, initialises its accumulator to ``None`` (never ``0.0``, the
       identity of a max-reduction over an empty set, which is what made an EMPTY region
       read as a perfectly tight one), and ``is_trustworthy`` rejects ``None`` BEFORE
       comparing against ``max_bin_ci_width``. Order matters: a comparison against ``None``
       raises rather than escalating, so the guard must come first.
    2. The region is chosen on the decision axis, tau-free. Eligibility is gated on
       ``cfg.wilson_floor``, and the dead ``_upper_half_ci_width`` name is gone.
    3. Every GatePolicyConfig tunable is bounded. ``__post_init__`` exists and names all
       nine fields plus ``n_bins``; ``min_auroc``'s lower bound is strictly above 0.5,
       because ``build_domain_models`` substitutes the sentinel 0.5 for single-class
       domains and documents that it "fails the health floor" -- true only while that bound
       holds. Non-finite values are rejected explicitly (NaN compares False against every
       bound and would otherwise pass).
    4. The policy is operator-reachable and fails as a USAGE error. ``merge_gate_ci``
       exposes a flag per tunable, builds the config via ``_policy_from_args``, and returns
       exit 2 on ``ConfigError`` -- never 1 (internal) and never 0, which CI reads as
       proceed-to-merge. ``--protected-auto-merge`` is deliberately absent: never
       auto-merging protected paths is an ADR 0005 design invariant, not an operator knob.
    5. The bin count is single-sourced and PASSED, not defaulted, at every call site --
       ``10`` was independently re-typed three times and agreed only by coincidence.
    6. Score-to-bin routing is single-sourced in ``_bin_of``: ``fit`` no longer carries the
       ``or b == bins - 1`` predicate that swept out-of-contract scores into the TOP bin
       while ``bin_index`` floored them to bin 0.
    7. The sample floor counts the fold it measures (``n=len(eval_recs)``), not the
       both-fold total that overstated it 2x.

Exit codes: 0 all checks passed; 1 one or more failed.
"""

from __future__ import annotations

import ast
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
    """Return the text of a repo-relative file (never imported -- the gate installs nothing)."""
    with open(os.path.join(_ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def _func(src: str, name: str) -> ast.FunctionDef | None:
    """The named function/method anywhere in the module, or ``None``."""
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _registered_flags(src: str) -> set[str]:
    """Every flag string actually passed to an ``add_argument`` call.

    Parsed, not grepped: the module *documents* why ``--protected-auto-merge`` is withheld,
    so a substring test would match that prose and report the flag as present. Only a real
    registration counts.
    """
    out: set[str] = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Attribute) and fn.attr == "add_argument":
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        out.add(arg.value)
    return out


def _decides_with_configured_policy(src: str) -> bool:
    """``run(...)`` must receive a built config, not a fresh ``GatePolicyConfig()``.

    A bare construction still legitimately appears in ``main`` as the source of the argparse
    defaults, so "is the literal absent?" is the wrong question -- it would fail on correct
    code. The question is what reaches the decision.
    """
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "run":
            return all(
                not (isinstance(a, ast.Call) and getattr(a.func, "id", None) == "GatePolicyConfig") for a in node.args
            )
    return False


def _guard_precedes_comparison(src: str) -> bool:
    """``is_trustworthy`` must test ``bin_ci_width is not None`` before comparing it.

    Positional, not merely present: ``x <= cfg.max`` against ``None`` raises a TypeError,
    which the CI entrypoint would surface as exit 1 rather than escalating. Checked on the
    unparsed source of the method so a reordering is caught.
    """
    fn = _func(src, "is_trustworthy")
    if fn is None:
        return False
    body = ast.unparse(fn)
    guard, compare = body.find("bin_ci_width is not None"), body.find("max_bin_ci_width")
    return guard != -1 and compare != -1 and guard < compare


def validate_f049() -> int:
    configure_logging()
    errors: list[str] = []

    store = _read(_AC, "outcome_store.py")
    gate = _read(_AC, "merge_gate.py")
    gate_ci = _read(_AC, "merge_gate_ci.py")
    calib = _read(_AC, "calibration.py")

    # --- 1/2. the fourth health floor measures something, on the right axis --------------
    width = _func(store, "_operating_bin_ci_width")
    _check(width is not None, "outcome_store defines _operating_bin_ci_width", errors)
    if width is not None:
        src = ast.unparse(width)
        _check(
            "float | None" in ast.unparse(width.returns) if width.returns else False,
            "_operating_bin_ci_width returns float | None (unmeasurable is not a float)",
            errors,
        )
        _check(
            "widest: float | None = None" in store,
            "the widest-CI accumulator starts at None, not 0.0 -- an empty region must not "
            "reduce to the identity of max() and read as a perfectly tight interval",
            errors,
        )
        _check(
            "cfg.wilson_floor" in src,
            "bin eligibility is gated on wilson_floor: a bin whose Wilson UPPER bound cannot "
            "reach the per-decision floor can never be an operating point, whatever tau becomes",
            errors,
        )
        _check(
            "cfg.n_bins" in src,
            "_operating_bin_ci_width bins by the policy's n_bins, not a local literal",
            errors,
        )
    _check(
        "_upper_half_ci_width" not in store,
        "the raw-upper-half scan is gone: decide() gates on the CALIBRATED p, so the raw "
        "score range was never 'where auto-merges actually happen'",
        errors,
    )
    _check(
        "bin_ci_width: float | None" in gate,
        "CalibratorHealth.bin_ci_width is Optional so 'unmeasurable' is representable",
        errors,
    )
    _check(
        _guard_precedes_comparison(gate),
        "is_trustworthy rejects an unmeasurable bin CI BEFORE comparing it to "
        "max_bin_ci_width (comparing None would raise, not escalate)",
        errors,
    )

    # --- 3. every autonomy tunable is bounded --------------------------------------------
    post_init = _func(gate, "__post_init__")
    _check(post_init is not None, "GatePolicyConfig validates at construction", errors)
    if post_init is not None:
        body = ast.unparse(post_init)
        for field in (
            "risk_target",
            "risk_ci_z",
            "min_calibration_n",
            "max_ece",
            "min_auroc",
            "max_bin_ci_width",
            "wilson_floor",
            "wilson_z",
            "n_bins",
        ):
            _check(field in body, f"GatePolicyConfig.__post_init__ bounds {field}", errors)
        _check(
            "'min_auroc', self.min_auroc, 0.5" in body,
            "min_auroc is bounded strictly above 0.5: build_domain_models substitutes that "
            "sentinel for single-class domains and documents that it fails the health floor",
            errors,
        )
    _check(
        "math.isfinite" in gate,
        "non-finite policy values are rejected explicitly -- NaN compares False against "
        "every bound and would otherwise satisfy a range test",
        errors,
    )
    _check(
        "n_bins: int = DEFAULT_N_BINS" in gate,
        "the bin count is a policy field defaulted from the single library source",
        errors,
    )

    # --- 4. reachable by an operator; a bad value is a usage error ------------------------
    registered = _registered_flags(gate_ci)
    for flag in (
        "--risk-target",
        "--risk-ci-z",
        "--min-calibration-n",
        "--max-ece",
        "--min-auroc",
        "--max-bin-ci-width",
        "--n-bins",
        "--wilson-floor",
        "--wilson-z",
    ):
        _check(flag in registered, f"merge_gate_ci exposes {flag}", errors)
    _check(
        "--protected-auto-merge" not in registered,
        "protected_auto_merge stays unreachable from CI: never auto-merging protected paths "
        "is an ADR 0005 design invariant, not an operator knob",
        errors,
    )
    _check(
        _func(gate_ci, "_policy_from_args") is not None,
        "merge_gate_ci maps its flags onto GatePolicyConfig",
        errors,
    )
    main = _func(gate_ci, "main")
    if main is not None:
        body = ast.unparse(main)
        policy_at = body.find("_policy_from_args")
        ctx_at = body.find("_load_context")
        _check(
            policy_at != -1 and ctx_at != -1 and policy_at < ctx_at,
            "the policy is built before the context, inside its own handler -- built later "
            "it would fall to the outer 'except Exception -> return 1' and report an "
            "operator's bad value as an internal fault",
            errors,
        )
        _check(
            "ConfigError" in body and "return 2" in body,
            "an out-of-range policy exits 2 (usage), never 1 and never 0 (proceed-to-merge)",
            errors,
        )
    _check(
        _decides_with_configured_policy(gate_ci),
        "the decision runs on the config built from the flags, not a bare "
        "GatePolicyConfig() that no operator can influence",
        errors,
    )

    # --- 5. one bin count, passed rather than defaulted ----------------------------------
    _check(
        "DEFAULT_N_BINS = 10" in calib,
        "calibration single-sources the reliability-bin count",
        errors,
    )
    for fn_name in ("reliability_bins", "expected_calibration_error"):
        node = _func(calib, fn_name)
        _check(
            node is not None and "DEFAULT_N_BINS" in ast.unparse(node.args),
            f"{fn_name} defaults its bin count to DEFAULT_N_BINS, not a re-typed literal",
            errors,
        )
    builder = _func(store, "build_domain_models")
    if builder is not None:
        body = ast.unparse(builder)
        _check(
            body.count("cfg.n_bins") >= 2 and "_operating_bin_ci_width(ev_raw, ev_labels, cfg)" in body,
            "build_domain_models routes the policy bin count into all three histograms -- "
            "the calibrator and the ECE take cfg.n_bins directly, the operating-region "
            "width takes cfg itself. They previously agreed only because the literal 10 "
            "was typed identically in three places",
            errors,
        )
        _check(
            "n=len(eval_recs)" in body,
            "min_calibration_n floors the HELD-OUT fold the other metrics are measured on, "
            "not the both-fold total that overstated the evidence 2x",
            errors,
        )
        _check(
            "n_total=len(recs)" in body,
            "the domain total is retained as a non-gating diagnostic",
            errors,
        )

    # --- 6. one routing implementation ---------------------------------------------------
    _check(_func(store, "_bin_of") is not None, "outcome_store defines _bin_of", errors)
    fit = _func(store, "fit")
    if fit is not None:
        body = ast.unparse(fit)
        _check(
            "_bin_of" in body,
            "fit routes through _bin_of so it cannot disagree with bin_index",
            errors,
        )
        _check(
            "b == bins - 1" not in body,
            "fit no longer sweeps out-of-contract scores into the TOP bin -- that predicate "
            "inflated a bin's accuracy with records bin_index would never route a query to",
            errors,
        )
    idx = _func(store, "bin_index")
    _check(
        idx is not None and "_bin_of" in ast.unparse(idx),
        "bin_index routes through _bin_of",
        errors,
    )

    return report(logger, "F-049", errors)


def main() -> int:
    return validate_f049()


if __name__ == "__main__":
    sys.exit(main())
