"""P5 report phase and the `all` chain.

``report`` renders claimed-vs-observed from the recorded observables + the signed rubric;
it refuses to run unsigned (marks come only from a signed rubric) and never emits a
recommendation. ``run_all`` chains P0->P2->P3->P5 and stops at the first FAIL/HALT/BLOCKED
in preflight or L1 — the phases that gate whether meaningful evidence exists. The ONE
deliberate exception is a BLOCKED L2 (the eval harness is not installed): L2 measures
adapter delta, not L1 evidence, so the chain records the BLOCKED phase, surfaces its
non-zero exit (the CLI returns the max exit code across phases), and still renders the
report from the L1 observables. A hard L2 FAIL stops the chain. An optionally injected
airgap runner (``all --with-airgap``) slots between L2 and the report under the same law:
BLOCKED continues to the report, FAIL/HALT stops. No OK verdict ever papers over a real
failure.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from backend_validation.airgap import AirgapVerdict
from backend_validation.logging_util import get_logger
from backend_validation.observables import ObservableLog
from backend_validation.phases import (
    STATUS_BLOCKED,
    STATUS_FAIL,
    STATUS_OK,
    PhaseResult,
    default_phase_io,
    run_l1,
    run_preflight,
)
from backend_validation.registry import RegistryError, load_probes_spec
from backend_validation.report import (
    build_cell_reports,
    render_airgap_report,
    render_claimed_vs_observed,
    write_report,
)
from backend_validation.rubric import RubricError, load_rubric, verify_signoff
from backend_validation.settings import Settings

logger = get_logger(__name__)


def run_report(
    subtree_root: Path,
    settings: Settings,
    *,
    run_id: str,
    now_fn: Callable[[], str],
) -> PhaseResult:
    reports_dir = settings.resolve_dir("reports_dir", subtree_root)
    artifacts_dir = settings.resolve_dir("artifacts_dir", subtree_root)
    try:
        spec = load_probes_spec(subtree_root / "PROBES.yaml")
        rules = load_rubric(subtree_root / "RUBRIC.md")
    except (RegistryError, RubricError) as exc:
        return PhaseResult("report", STATUS_FAIL, f"TCB artifacts unreadable: {exc}")

    signoff = verify_signoff(subtree_root, spec.signoff, rules)
    if not signoff.ok:
        return PhaseResult(
            "report",
            STATUS_BLOCKED,
            "cannot render marks from an unsigned rubric: " + "; ".join(signoff.reasons[:2]),
        )

    log = ObservableLog(artifacts_dir / run_id / "observables.jsonl")
    observables = log.read_all()
    if not observables:
        return PhaseResult("report", STATUS_BLOCKED, f"no observables recorded for run {run_id!r}; run L1 first")

    reports = build_cell_reports(spec, rules, observables)
    text = render_claimed_vs_observed(reports)
    out_path = write_report(reports_dir / "claimed_vs_observed.md", text)
    # Re-render the air-gap report from persisted P4 verdicts when this run has them, so
    # `report --run-id <old>` reproduces the FULL evidence set without re-running docker.
    airgap_artifacts: tuple[str, ...] = ()
    verdicts_path = artifacts_dir / run_id / "airgap" / "verdicts.json"
    if verdicts_path.exists():
        try:
            payload = json.loads(verdicts_path.read_text(encoding="utf-8"))
            verdicts = [AirgapVerdict.from_dict(entry) for entry in payload["verdicts"]]
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            # Corrupt persisted evidence must fail LOUD, never render a partial report.
            return PhaseResult("report", STATUS_FAIL, f"airgap verdicts unreadable at {verdicts_path}: {exc}")
        airgap_path = write_report(reports_dir / "airgap_report.md", render_airgap_report(verdicts))
        airgap_artifacts = (str(airgap_path),)
    unresolved = [report for report in reports if report.observed in ("BLOCKED", "not-probed")]
    logger.info(
        "report: %d cell rows from %d observables (%d unprobed/blocked)",
        len(reports),
        len(observables),
        len(unresolved),
    )
    return PhaseResult(
        "report",
        STATUS_OK,
        f"rendered {len(reports)} cell rows ({len(unresolved)} unprobed/blocked); evidence only, no platform selection",
        artifacts=(str(out_path), *airgap_artifacts),
    )


def run_all(
    subtree_root: Path,
    settings: Settings,
    *,
    run_id: str,
    now_fn: Callable[[], str],
    l2_runner: Callable[..., PhaseResult],
    airgap_runner: Callable[..., PhaseResult] | None = None,
) -> list[PhaseResult]:
    """Chain P0 -> P2 -> P3 [-> P4] -> P5, stopping at the first non-OK phase.

    Deploy (P1) requires live docker and is NOT part of the offline chain; air-gap (P4)
    joins only when ``airgap_runner`` is injected (``all --with-airgap``) — with the
    default ``None`` the chain is byte-identical to before. ``l2_runner`` is injected to
    avoid importing the harness at module load (harness-independence). A BLOCKED airgap
    (docker/overlays not ready) still renders the report from the L1 observables — the
    same law as a BLOCKED L2 — while FAIL/HALT stops the chain.
    """
    io = default_phase_io()
    results: list[PhaseResult] = []

    preflight = run_preflight(subtree_root, settings, io)
    results.append(preflight)
    if preflight.status != STATUS_OK:
        return results

    l1 = run_l1(subtree_root, settings, io, run_id=run_id)
    results.append(l1)
    if l1.status != STATUS_OK:
        return results

    l2 = l2_runner(subtree_root, settings, run_id=run_id, now_fn=now_fn)
    results.append(l2)
    if l2.status not in (STATUS_OK, STATUS_BLOCKED):
        # BLOCKED L2 (harness absent) is an allowed, recorded outcome; a hard FAIL stops.
        return results

    if airgap_runner is not None:
        airgap = airgap_runner(subtree_root, settings, run_id=run_id, now_fn=now_fn)
        results.append(airgap)
        if airgap.status not in (STATUS_OK, STATUS_BLOCKED):
            return results

    results.append(run_report(subtree_root, settings, run_id=run_id, now_fn=now_fn))
    return results
