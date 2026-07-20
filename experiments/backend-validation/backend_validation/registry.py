"""PROBES.yaml parsing/validation and the probe-implementation registry.

PROBES.yaml is a signed TCB artifact; this module gives it teeth: strict typed models
(unknown fields are errors), uniqueness checks, and two-way cross-validation between the
declared probe ids and the registered implementations — an id in YAML with no code, or
code with no YAML entry, is an ERROR, never a silent skip.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from backend_validation import CLAIM_TBD, MARK_ABSENT, MARK_FULL, MARK_PARTIAL, VALID_CLAIMS

_PROBE_ID = re.compile(r"^(l1|l2|l3|control)\.[a-z0-9_.]+$")

Classification = Literal["api-probeable", "config-probeable", "human-only", "doc-only"]
Repetition = Literal["deterministic", "judge_k3"]
Expectation = Literal["pass", "fail"]


class RegistryError(ValueError):
    """Raised for malformed or inconsistent PROBES.yaml content."""


class Predicate(BaseModel):
    """One expected observable: `operation`'s flat view must have `field == equals`."""

    model_config = ConfigDict(extra="forbid")

    operation: str
    field: str
    equals: bool | int | float | str


class ProbeDecl(BaseModel):
    model_config = ConfigDict(extra="forbid")

    probe_id: str
    layer: Literal["l1", "l2", "l3"]
    expectation: dict[str, Expectation]
    judge_required: bool = False
    expected_observables: list[Predicate] = Field(min_length=1)

    @field_validator("probe_id")
    @classmethod
    def _probe_id_shape(cls, value: str) -> str:
        if not _PROBE_ID.fullmatch(value):
            raise ValueError(f"probe_id {value!r} must look like l1.area.name")
        return value


class CellDecl(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    area: str
    classification: Classification
    repetition: Repetition
    claimed: dict[str, str]
    human_followup: bool = False
    probes: list[ProbeDecl] = Field(default_factory=list)

    @field_validator("claimed")
    @classmethod
    def _claims_are_marks(cls, value: dict[str, str]) -> dict[str, str]:
        for backend, mark in value.items():
            if mark not in VALID_CLAIMS:
                raise ValueError(f"claimed[{backend!r}] must be one of {VALID_CLAIMS}, got {mark!r}")
        return value


class SyntheticControl(BaseModel):
    model_config = ConfigDict(extra="forbid")

    probe_id: str
    applies_to: list[str] = Field(min_length=1)
    expectation: Literal["fail"]  # a synthetic control that expects success is meaningless
    expected_observables: list[Predicate] = Field(min_length=1)


class Controls(BaseModel):
    model_config = ConfigDict(extra="forbid")

    synthetic: list[SyntheticControl] = Field(default_factory=list)


class SignoffBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signed_off: bool
    signed_by: str | None = None
    signed_date: str | None = None


class SourceMatrix(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_ref: str
    transcribed_by: Literal["human"]
    transcription_source: str


class ProbesSpec(BaseModel):
    """The whole signed PROBES.yaml document."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    source_matrix: SourceMatrix
    marks: dict[str, str]
    backends: list[str] = Field(min_length=1)
    cells: list[CellDecl]
    controls: Controls = Field(default_factory=Controls)
    signoff: SignoffBlock

    @field_validator("marks")
    @classmethod
    def _marks_match_package_constants(cls, value: dict[str, str]) -> dict[str, str]:
        expected = {"full": MARK_FULL, "partial": MARK_PARTIAL, "absent": MARK_ABSENT}
        if value != expected:
            raise ValueError(f"marks must be exactly {expected}, got {value}")
        return value

    def cell(self, cell_id: str) -> CellDecl:
        for candidate in self.cells:
            if candidate.id == cell_id:
                return candidate
        raise RegistryError(f"unknown cell id {cell_id!r}")

    def declared_probe_ids(self) -> set[str]:
        ids = {probe.probe_id for cell in self.cells for probe in cell.probes}
        ids.update(control.probe_id for control in self.controls.synthetic)
        return ids

    def unresolved_claims(self) -> list[tuple[str, str]]:
        """(cell_id, backend) pairs still carrying CLAIM_TBD — must be zero at sign-off."""
        return [
            (cell.id, backend)
            for cell in self.cells
            for backend, mark in sorted(cell.claimed.items())
            if mark == CLAIM_TBD
        ]


def _check_consistency(spec: ProbesSpec) -> None:
    backends = set(spec.backends)
    cell_ids = [cell.id for cell in spec.cells]
    if len(cell_ids) != len(set(cell_ids)):
        raise RegistryError("duplicate cell ids in PROBES.yaml")
    seen_probe_ids: set[str] = set()
    for cell in spec.cells:
        if set(cell.claimed) != backends:
            raise RegistryError(f"cell {cell.id!r} claimed marks must cover exactly {sorted(backends)}")
        if cell.classification in ("human-only", "doc-only") and cell.probes:
            raise RegistryError(f"cell {cell.id!r} is {cell.classification} and must not declare probes")
        for probe in cell.probes:
            if probe.probe_id in seen_probe_ids:
                raise RegistryError(f"duplicate probe_id {probe.probe_id!r}")
            seen_probe_ids.add(probe.probe_id)
            if set(probe.expectation) != backends:
                raise RegistryError(f"probe {probe.probe_id!r} expectation must cover exactly {sorted(backends)}")
    for control in spec.controls.synthetic:
        if control.probe_id in seen_probe_ids:
            raise RegistryError(f"duplicate probe_id {control.probe_id!r}")
        seen_probe_ids.add(control.probe_id)
        unknown = set(control.applies_to) - backends
        if unknown:
            raise RegistryError(f"control {control.probe_id!r} applies_to unknown backends {sorted(unknown)}")


def load_probes_spec(path: Path) -> ProbesSpec:
    """Parse and validate PROBES.yaml; any inconsistency is an error, never a warning."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RegistryError(f"cannot read {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise RegistryError(f"{path} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise RegistryError(f"{path} must contain a mapping at the top level")
    try:
        spec = ProbesSpec.model_validate(raw)
    except ValidationError as exc:
        raise RegistryError(f"{path} failed validation: {exc}") from exc
    _check_consistency(spec)
    return spec


# --------------------------------------------------------------- implementations
# A probe implementation receives a client and context and returns raw payloads the
# runner wraps into Observables; the registry only maps ids to callables.
ProbeFunc = Callable[..., Any]

_PROBE_IMPLS: dict[str, ProbeFunc] = {}


def register(probe_id: str) -> Callable[[ProbeFunc], ProbeFunc]:
    def _decorator(func: ProbeFunc) -> ProbeFunc:
        if probe_id in _PROBE_IMPLS:
            raise RegistryError(f"probe {probe_id!r} registered twice")
        _PROBE_IMPLS[probe_id] = func
        return func

    return _decorator


def registered_probe_ids() -> set[str]:
    return set(_PROBE_IMPLS)


def get_probe(probe_id: str) -> ProbeFunc:
    try:
        return _PROBE_IMPLS[probe_id]
    except KeyError as exc:
        raise RegistryError(f"probe {probe_id!r} has no registered implementation") from exc


def cross_validate(spec: ProbesSpec, registered: Iterable[str], *, layers: tuple[str, ...] = ("l1",)) -> list[str]:
    """Two-way id check for the given layers; returns a list of problems (empty = OK)."""
    registered_set = set(registered)
    problems: list[str] = []
    declared: set[str] = set()
    for cell in spec.cells:
        for probe in cell.probes:
            if probe.layer in layers:
                declared.add(probe.probe_id)
    declared.update(control.probe_id for control in spec.controls.synthetic)
    for probe_id in sorted(declared - registered_set):
        problems.append(f"declared in PROBES.yaml but not implemented: {probe_id}")
    for probe_id in sorted(registered_set - declared):
        problems.append(f"implemented but not declared in PROBES.yaml: {probe_id}")
    return problems
