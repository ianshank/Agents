"""P5 report renderers: claimed-vs-observed, airgap, effort. NO recommendation section.

The report presents evidence in two explicitly-labelled columns — ``claimed (matrix)`` vs
``observed (mechanical)`` — echoing the repo's passive-vs-authoritative label model
(agent-core outcome_store). It computes marks ONLY through the signed rubric, routes
anything the rubric cannot resolve to ``HUMAN``, and never emits a recommendation or verdict:
platform selection is a human label (spec §5). A test asserts the forbidden headings never
appear.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from backend_validation import CLAIM_TBD, MARK_HUMAN
from backend_validation.airgap import AirgapVerdict
from backend_validation.observables import Observable
from backend_validation.registry import CellDecl, ProbesSpec
from backend_validation.repetition import any_flaky, evaluate_predicates, majorities
from backend_validation.rubric import RubricRules, compute_mark

# A recommendation shows up as a heading ("## Recommendation") or as selection language,
# never as an incidental word — so a disclaimer like "presents no recommendation" is fine.
_FORBIDDEN_HEADING_WORDS = ("recommendation", "verdict")
_FORBIDDEN_PHRASES = ("we recommend", "our choice", "our verdict", "the winner is", "winner is", "we suggest choosing")


@dataclass(frozen=True)
class CellReport:
    cell_id: str
    area: str
    backend: str
    claimed: str
    observed: str
    delta: str  # match | claim-overstated | claim-understated | not-probed | BLOCKED
    flaky: bool
    run_count: int


def _delta(claimed: str, observed: str) -> str:
    order = {"—": 0, "◐": 1, "●": 2}
    if observed in (MARK_HUMAN, "not-probed", "BLOCKED"):
        return observed if observed != MARK_HUMAN else "human"
    if claimed == CLAIM_TBD:
        return "claim-unknown"
    if claimed == observed:
        return "match"
    if order.get(claimed, 0) > order.get(observed, 0):
        return "claim-overstated"
    return "claim-understated"


def score_cell(
    cell: CellDecl,
    backend: str,
    rules: RubricRules,
    observables: Sequence[Observable],
) -> CellReport:
    """Turn a cell's observables into a rubric mark + claimed-vs-observed delta."""
    claimed = cell.claimed.get(backend, CLAIM_TBD)
    if cell.classification in ("human-only", "doc-only"):
        return CellReport(cell.id, cell.area, backend, claimed, "not-probed", "not-probed", False, 0)
    probe = next((p for p in cell.probes if p.expectation.get(backend) == "pass"), None)
    if probe is None:
        # No pass-probe for this backend (e.g. an expected-fail control cell) -> not marked.
        return CellReport(cell.id, cell.area, backend, claimed, "not-probed", "not-probed", False, 0)
    cell_obs = [o for o in observables if o.probe_id == probe.probe_id and o.backend == backend]
    if not cell_obs:
        return CellReport(cell.id, cell.area, backend, claimed, "BLOCKED", "BLOCKED", False, 0)
    verdicts = evaluate_predicates(probe.expected_observables, cell_obs)
    mark = compute_mark(rules, cell.id, majorities(verdicts))
    run_count = len({o.rep_index for o in cell_obs})
    return CellReport(cell.id, cell.area, backend, claimed, mark, _delta(claimed, mark), any_flaky(verdicts), run_count)


def build_cell_reports(
    spec: ProbesSpec,
    rules: RubricRules,
    observables: Sequence[Observable],
) -> list[CellReport]:
    reports: list[CellReport] = []
    for cell in spec.cells:
        for backend in spec.backends:
            reports.append(score_cell(cell, backend, rules, observables))
    return reports


def render_claimed_vs_observed(reports: Sequence[CellReport]) -> str:
    lines = [
        "# Claimed vs Observed",
        "",
        "Evidence only. `claimed (matrix)` is the transcribed capability claim; "
        "`observed (mechanical)` is the mark the signed rubric computed from probe observables. "
        "This report does not select a platform — that is a human decision.",
        "",
        "| Cell | Area | Backend | claimed (matrix) | observed (mechanical) | delta | flaky | runs |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for report in reports:
        flaky = "yes" if report.flaky else ""
        lines.append(
            f"| {report.cell_id} | {report.area} | {report.backend} | {report.claimed} | "
            f"{report.observed} | {report.delta} | {flaky} | {report.run_count} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_airgap_report(verdicts: Sequence[AirgapVerdict]) -> str:
    lines = [
        "# Air-Gap Report",
        "",
        "Dual-scored: **as-shipped** (default telemetry) vs **after documented opt-out**. "
        "The matrix `Air-Gapped: Yes` claim is confirmed only when the opt-out run shows zero "
        "egress attempts.",
        "",
        "| Backend | as-shipped egress | opt-out egress | air-gapped confirmed | mechanism | degraded |",
        "|---|---|---|---|---|---|",
    ]
    for verdict in verdicts:
        as_dom = ", ".join(verdict.as_shipped.observation.attempted_domains) if verdict.as_shipped.observation else "?"
        opt_dom = ", ".join(verdict.opt_out.observation.attempted_domains) if verdict.opt_out.observation else "?"
        mechanism = verdict.opt_out.observation.mechanism if verdict.opt_out.observation else "none"
        degraded = "yes" if (verdict.opt_out.observation and verdict.opt_out.observation.degraded) else ""
        lines.append(
            f"| {verdict.backend} | {as_dom or 'none'} | {opt_dom or 'none'} | "
            f"{'yes' if verdict.air_gapped_confirmed else 'no'} | {mechanism} | {degraded} |"
        )
    lines.append("")
    return "\n".join(lines)


def assert_no_recommendation(text: str) -> None:
    """Guard the invariant at render time: the report must carry no recommendation/verdict."""
    lowered = text.lower()
    found: list[str] = []
    for line in text.splitlines():
        stripped = line.strip().lower()
        if stripped.startswith("#") and any(word in stripped for word in _FORBIDDEN_HEADING_WORDS):
            found.append(line.strip())
    found.extend(phrase for phrase in _FORBIDDEN_PHRASES if phrase in lowered)
    if found:
        raise ValueError(f"report must contain no recommendation/verdict language; found: {found}")


def write_report(path: Path, text: str) -> Path:
    assert_no_recommendation(text)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
