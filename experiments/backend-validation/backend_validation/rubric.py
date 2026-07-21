"""Deterministic rubric application and TCB sign-off verification.

The rubric lives in RUBRIC.md as exactly one fenced YAML block after the
``<!-- rubric:machine -->`` marker: one human-signed document, one machine input.
This module maps "which expected observables held" to a mark and verifies the SIGNOFF
hashes; it never invents marks (unresolvable → HUMAN, spec scoring rule 4).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend_validation import MARK_ABSENT, MARK_FULL, MARK_PARTIAL
from backend_validation.observables import Observable
from backend_validation.registry import Predicate, SignoffBlock

_MACHINE_MARKER = "<!-- rubric:machine -->"
_FENCE = re.compile(r"```yaml\n(.*?)```", re.DOTALL)
_SIGNOFF_LINE = re.compile(r"^sha256 (?P<digest>[0-9a-f]{64})\s+(?P<name>PROBES\.yaml|RUBRIC\.md)$")


class RubricError(ValueError):
    """Raised for structural rubric problems (missing/duplicate machine block, bad rules)."""


class MarkRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    all_expected_hold: bool | None = None
    some_expected_hold: bool | None = None
    min_expected_fraction: float | None = Field(default=None, ge=0.0, le=1.0)
    otherwise: bool | None = None


class DefaultMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full: MarkRule
    partial: MarkRule
    absent: MarkRule


class Override(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cell: str
    partial: MarkRule


class Mapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default: DefaultMapping
    overrides: list[Override] = Field(default_factory=list)


class HaltRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unexpected_control_pass: bool


class RubricRules(BaseModel):
    """The parsed machine block of RUBRIC.md."""

    model_config = ConfigDict(extra="forbid")

    rubric_version: int
    mapping: Mapping
    flags: dict[str, str]
    halt: HaltRules
    signoff: SignoffBlock

    def partial_rule_for(self, cell_id: str) -> MarkRule:
        for override in self.mapping.overrides:
            if override.cell == cell_id:
                return override.partial
        return self.mapping.default.partial


def extract_machine_block(rubric_text: str) -> str:
    """Return the YAML source of the single machine block; zero or many is an error."""
    marker_at = rubric_text.find(_MACHINE_MARKER)
    if marker_at < 0:
        raise RubricError(f"RUBRIC.md has no {_MACHINE_MARKER} marker")
    fences: list[str] = _FENCE.findall(rubric_text[marker_at:])
    if len(fences) != 1:
        raise RubricError(f"expected exactly ONE fenced yaml block after the marker, found {len(fences)}")
    return fences[0]


def load_rubric(path: Path) -> RubricRules:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RubricError(f"cannot read {path}: {exc}") from exc
    block = extract_machine_block(text)
    try:
        raw = yaml.safe_load(block)
    except yaml.YAMLError as exc:
        raise RubricError(f"rubric machine block is not valid YAML: {exc}") from exc
    try:
        return RubricRules.model_validate(raw)
    except ValidationError as exc:
        raise RubricError(f"rubric machine block failed validation: {exc}") from exc


# ------------------------------------------------------------------ evaluation
def flat_view(observable: Observable) -> dict[str, object]:
    """The namespace predicates evaluate against: outcome fields + probe evidence extras."""
    view: dict[str, object] = {
        "status": observable.outcome.status,
        "latency_ms": observable.outcome.latency_ms,
        "retries": observable.outcome.retries,
        "stderr": observable.outcome.stderr,
    }
    view.update(observable.extra)
    return view


def predicate_holds(predicate: Predicate, rep_observables: list[Observable]) -> bool:
    """True iff ANY observable of that operation in this repetition satisfies the predicate."""
    for observable in rep_observables:
        if observable.outcome.operation != predicate.operation:
            continue
        if flat_view(observable).get(predicate.field) == predicate.equals:
            return True
    return False


def compute_mark(rules: RubricRules, cell_id: str, held: list[bool]) -> str:
    """Map predicate outcomes to a mark. ``held`` has one entry per expected observable."""
    if not held:
        raise RubricError(f"cell {cell_id!r} has no predicate outcomes to map")
    if all(held):
        return MARK_FULL
    partial_rule = rules.partial_rule_for(cell_id)
    if partial_rule.min_expected_fraction is not None:
        fraction = sum(held) / len(held)
        return MARK_PARTIAL if fraction >= partial_rule.min_expected_fraction else MARK_ABSENT
    if any(held):
        return MARK_PARTIAL
    return MARK_ABSENT


# -------------------------------------------------------------------- sign-off
@dataclass(frozen=True)
class SignoffStatus:
    ok: bool
    reasons: tuple[str, ...] = ()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_signoff(root: Path, probes_signoff: SignoffBlock, rubric_rules: RubricRules) -> SignoffStatus:
    """Verify the human sign-off: both flags true AND SIGNOFF hashes match both files.

    Agents never write the SIGNOFF file; this function only ever READS it. A signed file
    that drifted after signing fails here mechanically.
    """
    reasons: list[str] = []
    if not probes_signoff.signed_off:
        reasons.append("PROBES.yaml signoff.signed_off is false")
    if not rubric_rules.signoff.signed_off:
        reasons.append("RUBRIC.md machine-block signoff.signed_off is false")
    signoff_path = root / "SIGNOFF"
    if not signoff_path.is_file():
        reasons.append("SIGNOFF file is missing (the human creates it at sign-off)")
        return SignoffStatus(ok=False, reasons=tuple(reasons))
    recorded: dict[str, str] = {}
    signed_by_present = False
    for line in signoff_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = _SIGNOFF_LINE.match(stripped)
        if match:
            recorded[match.group("name")] = match.group("digest")
        elif stripped.startswith("signed_by:") and stripped.split(":", 1)[1].strip():
            signed_by_present = True
        else:
            reasons.append(f"SIGNOFF contains an unrecognized line: {stripped!r}")
    for name in ("PROBES.yaml", "RUBRIC.md"):
        if name not in recorded:
            reasons.append(f"SIGNOFF is missing a sha256 line for {name}")
        elif recorded[name] != _sha256(root / name):
            reasons.append(f"SIGNOFF hash for {name} does not match the file (post-signing drift?)")
    if not signed_by_present:
        reasons.append("SIGNOFF is missing a non-empty signed_by: line")
    return SignoffStatus(ok=not reasons, reasons=tuple(reasons))
