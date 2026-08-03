#!/usr/bin/env python3
"""Validation script for F-047 — proxy-correlation measurement, PPI++ estimator, propensity.

Deterministic and offline: reads module / workflow TEXT only (no ``agent_core`` import,
which the validation gate does not install). Pins the invariants that make the new
reporting honest, so a future edit cannot silently regress them.

    1. The GATE is untouched: merge_gate.decide() still REACHES a Wilson bound, and neither
       merge_gate nor merge_gate_ci imports the estimator or either report module -- no new
       code path can reach an auto-merge decision. Both halves are checked with ``ast``, not
       substrings: decide() calls ``_wilson_bound``, so ``"wilson_interval(" in src`` matched
       elsewhere in the module and proved nothing, and ``import agent_core.ppi as p`` shares
       no ``"import ppi"`` substring at all.
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


def _called_names(node: ast.AST) -> set[str]:
    """Every function name called anywhere inside ``node``, bare or attribute-style."""
    out: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            fn = sub.func
            if isinstance(fn, ast.Name):
                out.add(fn.id)
            elif isinstance(fn, ast.Attribute):
                out.add(fn.attr)
    return out


def reaches_call(src: str, entry: str, target: str) -> bool:
    """``True`` when ``entry`` reaches a call to ``target`` within this module.

    Follows the intra-module call graph instead of grepping the file, because a substring
    match proves only that the name occurs *somewhere*. ``merge_gate.decide()`` calls
    ``_wilson_bound``, which calls ``wilson_interval`` -- so ``"wilson_interval(" in src``
    passed while establishing nothing at all about ``decide``. The invariant this file
    exists to defend is precisely that ``decide`` still computes a Wilson bound.
    """
    tree = ast.parse(src)
    funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    if entry not in funcs:
        return False
    seen: set[str] = set()
    stack = [entry]
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        called = _called_names(funcs[name])
        if target in called:
            return True
        stack.extend(c for c in called if c in funcs and c not in seen)
    return False


def imports_module(src: str, banned: str) -> bool:
    """``True`` when ``src`` imports ``banned`` in ANY form.

    Covers what substring matching missed -- ``import agent_core.ppi as p`` shares no
    ``"import ppi"`` substring, so the previous check waved it straight through.
    """
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            for alias in node.names:  # import a.b.c  /  import a.b.c as d
                if banned in alias.name.split("."):
                    return True
        elif isinstance(node, ast.ImportFrom):
            # from .banned import x  /  from pkg.banned import x
            if banned in (node.module or "").split("."):
                return True
            # from . import banned  /  from pkg import banned
            if any(alias.name == banned for alias in node.names):
                return True
    return False


def validate_f047() -> int:
    """Assert every F-047 invariant; returns 0 when all pass, 1 otherwise."""
    configure_logging()
    errors: list[str] = []

    ppi = _read(_AC, "ppi.py")
    proxy_analysis = _read(_AC, "proxy_analysis.py")
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
    #    Syntax-aware on purpose: both halves of this were substring checks that could pass
    #    for the wrong reason (see reaches_call / imports_module).
    _check(
        reaches_call(gate, "decide", "wilson_interval"),
        "merge_gate.decide() still reaches a Wilson bound (call graph, not a substring)",
        errors,
    )
    for name, src in (("merge_gate", gate), ("merge_gate_ci", gate_ci)):
        for banned in ("ppi", "proxy_eval", "calibration_report"):
            _check(
                not imports_module(src, banned),
                f"{name} does not import {banned} in any form (no new path to a gate decision)",
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
        "if degenerate is None and len({int(y) for y in ys}) == 2:" in proxy_analysis,
        "proxy_analysis withholds AUROC on a degenerate slice",
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
    # The renderer is SERIALISATION -- its output is pasted into a dispatch command, so it
    # must parse back to a usable probability. Fixed-point rendering collapsed 1e-7 to
    # "0.000000", which the contract then rejects.
    _check(
        'f"{value:.{PROPENSITY_SIGFIGS}g}"' in sampler,
        "format_propensity renders significant figures, so tiny propensities round-trip",
        errors,
    )
    # Scoped to the propensity format spec in the module that owns it -- narrow enough not
    # to fire on unrelated code. Two sites (the selected.txt writer and a log line) bypassed
    # the helper with a hand-rolled `.6f`, so the producer could emit a value its own
    # consumer rejects. Defining a shared renderer is not the same as using it.
    # Matches the format-spec SYNTAX (`:.6f` / `%.6f`), not the bare string -- the bare form
    # also matched prose in a comment explaining this very rule.
    for name, src in (("audit_sampler", sampler), ("audit_issue_sync", issue_sync)):
        _check(
            ":.6f" not in src and "%.6f" not in src,
            f"{name} renders every propensity through format_propensity, never a local .6f",
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
    """CLI entry point."""
    return validate_f047()


if __name__ == "__main__":
    sys.exit(main())
