"""CI entrypoint for the calibrated merge gate (mirrors check_protected_changes.py).

Run as a module:  ``python -m agent_core.merge_gate_ci --store <jsonl> [...]``.

Consumes upstream results rather than recomputing them:
  * mech_pass        <- regression_gate.py exit status (net-new findings?)
  * touches_protected<- eval_protected_paths.py classification
  * raw_confidence   <- the agent's self-reported confidence at PR time
  * domain           <- change domain tag

Per-domain calibrators/tau/health are built from HUMAN_AUDIT records only.

Exit codes (stable contract for CI):
  0  AUTO_MERGE  -> CI proceeds to merge
  10 ESCALATE    -> CI applies a needs-human-review label, leaves PR open
  20 REJECT      -> CI fails the check (mechanical ground-truth failure)
  2  usage error (argparse);  1 unexpected internal error
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .logging_util import configure_logging, get_logger
from .merge_gate import ChangeContext, GateDecision, GatePolicyConfig, decide
from .outcome_store import LabelSource, OutcomeStore, build_domain_models

logger = get_logger(__name__)

EXIT = {
    GateDecision.AUTO_MERGE: 0,
    GateDecision.ESCALATE: 10,
    GateDecision.REJECT: 20,
}


def _load_context(args: argparse.Namespace) -> ChangeContext:
    if args.context:
        d = json.loads(Path(args.context).read_text(encoding="utf-8"))
        return ChangeContext(
            mech_pass=bool(d["mech_pass"]),
            touches_protected=bool(d["touches_protected"]),
            raw_confidence=float(d["raw_confidence"]),
            domain=str(d["domain"]),
        )
    return ChangeContext(
        mech_pass=args.mech_pass,
        touches_protected=args.touches_protected,
        raw_confidence=args.raw_confidence,
        domain=args.domain,
    )


def run(ctx: ChangeContext, store: OutcomeStore, cfg: GatePolicyConfig) -> tuple[GateDecision, str]:
    models = build_domain_models(store, cfg)
    m = models.get(ctx.domain)
    if m is None:
        # cold start: no audit data for this domain -> safe default
        d = decide(ctx, None, None, None, 0, 0, cfg)
        return d, f"no audit data for domain '{ctx.domain}' (cold start)"

    # bin stats at the change's operating point, for the Wilson floor check.
    # Group by bin INDEX, not predicted accuracy: distinct bins can share the
    # same accuracy (e.g. several 100% bins) and grouping by value would conflate
    # them, inflating bin_n and letting thin data piggyback on a populated bin.
    p = m.calibrator.predict(ctx.raw_confidence)
    target_bin = m.calibrator.bin_index(ctx.raw_confidence)
    audit = [
        r
        for r in store.resolved().values()
        if r.domain == ctx.domain
        and r.label_source == LabelSource.HUMAN_AUDIT.value
        and r.label is not None
    ]
    same_bin = [r for r in audit if m.calibrator.bin_index(r.raw_confidence) == target_bin]
    bin_n = len(same_bin)
    bin_succ = sum(1 for r in same_bin if r.label)

    d = decide(ctx, m.calibrator, m.health, m.tau, bin_succ, bin_n, cfg)
    why = (
        f"p={p:.3f} tau={m.tau} healthy={m.health.is_trustworthy(cfg)} "
        f"n={m.health.n} ece={m.health.ece:.3f} auroc={m.health.auroc:.3f} "
        f"bin={bin_succ}/{bin_n}"
    )
    return d, why


def _append_audit(path: str, ctx: ChangeContext, decision: GateDecision, why: str) -> None:
    """Persist the decision so every auto-merge call is auditable after the fact."""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "domain": ctx.domain,
        "raw_confidence": ctx.raw_confidence,
        "mech_pass": ctx.mech_pass,
        "touches_protected": ctx.touches_protected,
        "decision": decision.value,
        "why": why,
    }
    with Path(path).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Calibrated merge gate (CI).")
    ap.add_argument("--store", required=True)
    ap.add_argument("--context", help="JSON file with the ChangeContext fields")
    ap.add_argument("--mech-pass", dest="mech_pass", action="store_true")
    ap.add_argument("--no-mech-pass", dest="mech_pass", action="store_false")
    ap.add_argument("--touches-protected", dest="touches_protected", action="store_true")
    ap.add_argument("--raw-confidence", type=float, default=0.0)
    ap.add_argument("--domain", default="")
    ap.add_argument("--audit-log", help="append the decision record here (JSONL)")
    ap.set_defaults(mech_pass=False, touches_protected=False)
    args = ap.parse_args(argv)

    configure_logging(level="INFO")
    try:
        ctx = _load_context(args)
        decision, why = run(ctx, OutcomeStore(args.store), GatePolicyConfig())
        if args.audit_log:
            _append_audit(args.audit_log, ctx, decision, why)
    except Exception as exc:  # unexpected -> exit 1, never silently pass
        print(f"merge-gate internal error: {exc}", file=sys.stderr)
        return 1

    logger.info("merge-gate DECISION=%s %s", decision.value, why)
    print(f"DECISION={decision.value}  {why}")
    return EXIT[decision]


if __name__ == "__main__":
    sys.exit(main())
