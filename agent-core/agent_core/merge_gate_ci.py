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
  2  usage error (argparse; an out-of-contract input value such as a raw_confidence
     outside [0, 1]; or an out-of-range gate-policy flag);  1 unexpected internal error
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import ConfigError
from .logging_util import configure_logging, get_logger
from .merge_gate import ChangeContext, GateDecision, GatePolicyConfig, decide
from .merge_seed import seed_pending
from .outcome_store import LabelSource, OutcomeStore, build_domain_models
from .protocols import Clock, SystemClock

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


def _add_policy_args(ap: argparse.ArgumentParser, policy: GatePolicyConfig) -> None:
    """Expose every gate tunable as a flag, defaulted from the dataclass itself.

    Defaults are read off ``policy`` rather than re-typed, so ``--help`` cannot drift from
    the documented field defaults. ADR 0005 SS3 calls tuning ``risk_target`` /
    ``min_calibration_n`` "a human decision"; until now there was no seam through which a
    human could make it without editing library source.

    ``--protected-auto-merge`` is deliberately absent -- see ``GatePolicyConfig``.
    """
    g = ap.add_argument_group("gate policy (see GatePolicyConfig / ADR 0005)")
    g.add_argument("--risk-target", type=float, default=policy.risk_target)
    g.add_argument("--risk-ci-z", type=float, default=policy.risk_ci_z)
    g.add_argument("--min-calibration-n", type=int, default=policy.min_calibration_n)
    g.add_argument("--max-ece", type=float, default=policy.max_ece)
    g.add_argument("--min-auroc", type=float, default=policy.min_auroc)
    g.add_argument("--max-bin-ci-width", type=float, default=policy.max_bin_ci_width)
    g.add_argument("--n-bins", type=int, default=policy.n_bins)
    g.add_argument("--wilson-floor", type=float, default=policy.wilson_floor)
    g.add_argument("--wilson-z", type=float, default=policy.wilson_z)


def _policy_from_args(args: argparse.Namespace) -> GatePolicyConfig:
    """Map parsed flags onto the frozen policy. Raises ``ConfigError`` on a bad value."""
    return GatePolicyConfig(
        risk_target=args.risk_target,
        risk_ci_z=args.risk_ci_z,
        min_calibration_n=args.min_calibration_n,
        max_ece=args.max_ece,
        min_auroc=args.min_auroc,
        max_bin_ci_width=args.max_bin_ci_width,
        n_bins=args.n_bins,
        wilson_floor=args.wilson_floor,
        wilson_z=args.wilson_z,
    )


def run(ctx: ChangeContext, store: OutcomeStore, cfg: GatePolicyConfig) -> tuple[GateDecision, str]:
    if cfg.protected_auto_merge:
        # Not reachable from the CLI by construction; log loudly if it is ever set in-process
        # so the audit trail shows that the protected-path layer was disabled for this run.
        logger.warning(
            "merge-gate: protected_auto_merge is ENABLED -- changes touching eval-defining "
            "paths can auto-merge, which ADR 0005 says they never should"
        )
    models = build_domain_models(store, cfg)
    m = models.get(ctx.domain)
    if m is None:
        # cold start: no audit data for this domain -> safe default
        logger.debug("merge-gate: domain=%s has no audit data (cold start)", ctx.domain)
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
    logger.debug("merge-gate: domain=%s decision=%s (%s)", ctx.domain, d.value, why)
    return d, why


def _append_audit(
    path: str, ctx: ChangeContext, decision: GateDecision, why: str, clock: Clock | None = None
) -> None:
    """Persist the decision so every auto-merge call is auditable after the fact."""
    record = {
        "ts": (clock or SystemClock()).now().isoformat(),
        "domain": ctx.domain,
        "raw_confidence": ctx.raw_confidence,
        "mech_pass": ctx.mech_pass,
        "touches_protected": ctx.touches_protected,
        "decision": decision.value,
        "why": why,
    }
    with Path(path).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")
    logger.debug("merge-gate: appended audit record to %s (decision=%s)", path, decision.value)


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
    # Default-off F-010 seam: when --seed-store is given and the gate AUTO_MERGEs,
    # write the initial pending OutcomeRecord so the labeller/audit sampler have
    # data to resolve. Absent flag -> behaviour is byte-identical to before.
    ap.add_argument("--seed-store", help="seed a pending OutcomeRecord here on AUTO_MERGE")
    ap.add_argument("--change-id", dest="change_id", help="change id for --seed-store")
    ap.add_argument("--merged-at", dest="merged_at", help="ISO-8601 merge time for --seed-store")
    ap.add_argument("--agent-version", dest="agent_version", help="keying hash for --seed-store")
    _add_policy_args(ap, GatePolicyConfig())
    ap.set_defaults(mech_pass=False, touches_protected=False)
    args = ap.parse_args(argv)

    configure_logging(level="INFO")
    try:
        try:
            # Built BEFORE the outer handler can see it: an out-of-range policy is the
            # operator's error, so it must exit 2 (usage), never 1 (internal) and never 0
            # (which CI reads as proceed-to-merge). argparse's `type=float` accepts "nan"
            # and "inf" happily -- GatePolicyConfig's isfinite guards are what stop them.
            cfg = _policy_from_args(args)
        except ConfigError as exc:
            print(f"merge-gate invalid policy: {exc!s}", file=sys.stderr)
            return 2
        try:
            ctx = _load_context(args)
        except (ValueError, KeyError, TypeError) as exc:
            # Bad input, not an internal fault: report it as a usage error (2) so CI shows
            # "fix your inputs" rather than "the gate broke" -- and never as 0, which CI
            # reads as proceed-to-merge. Covers an out-of-contract confidence (ValueError),
            # malformed JSON (JSONDecodeError, a ValueError), a context file missing a
            # required field (KeyError), and a null where a value belongs (TypeError).
            # An unreadable/absent --context path stays an internal error: that is the
            # environment failing, not the caller passing a bad value.
            print(f"merge-gate invalid input: {exc!s} ({type(exc).__name__})", file=sys.stderr)
            return 2
        decision, why = run(ctx, OutcomeStore(args.store), cfg)
        if args.audit_log:
            _append_audit(args.audit_log, ctx, decision, why)
        if args.seed_store and args.change_id and decision == GateDecision.AUTO_MERGE:
            seed_pending(
                OutcomeStore(args.seed_store),
                args.change_id,
                ctx.domain,
                ctx.raw_confidence,
                merged_at=args.merged_at,
                agent_version=args.agent_version,
            )
    except Exception as exc:  # unexpected -> exit 1, never silently pass
        print(f"merge-gate internal error: {exc}", file=sys.stderr)
        return 1

    logger.info("merge-gate DECISION=%s %s", decision.value, why)
    print(f"DECISION={decision.value}  {why}")
    return EXIT[decision]


if __name__ == "__main__":
    sys.exit(main())
