"""Unit tests for PROBES.yaml parsing, consistency rules, and the probe registry."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest
import yaml

from backend_validation import CLAIM_TBD, MARK_PARTIAL
from backend_validation.registry import (
    RegistryError,
    cross_validate,
    get_probe,
    load_probes_spec,
    register,
    registered_probe_ids,
)

SUBTREE = Path(__file__).resolve().parents[1]
PROBES = SUBTREE / "PROBES.yaml"


def _write_spec(tmp_path: Path, mutate: Any) -> Path:
    data = yaml.safe_load(PROBES.read_text(encoding="utf-8"))
    mutate(data)
    path = tmp_path / "PROBES.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


# ------------------------------------------------------------- the committed file
def test_committed_probes_file_parses_and_is_consistent() -> None:
    spec = load_probes_spec(PROBES)
    assert spec.backends == ["langfuse", "opik"]
    assert len(spec.cells) == 14  # the full Grid - App Eval row set from the spec
    assert spec.signoff.signed_off is False  # ships unsigned; the human signs at P0


def test_committed_claims_match_the_spec_statements() -> None:
    spec = load_probes_spec(PROBES)
    assert spec.cell("rag.metrics").claimed["langfuse"] == MARK_PARTIAL  # stated in spec section 2
    guardrails = spec.cell("guardrails")
    assert guardrails.probes[0].expectation == {"langfuse": "fail", "opik": "pass"}
    redteam = spec.cell("red.teaming")
    assert redteam.probes[0].expectation == {"langfuse": "fail", "opik": "fail"}


def test_unresolved_claims_lists_every_claim_tbd_cell() -> None:
    spec = load_probes_spec(PROBES)
    unresolved = spec.unresolved_claims()
    assert ("tracing.observability", "langfuse") in unresolved
    assert ("rag.metrics", "langfuse") not in unresolved  # that one is transcribed
    assert all(mark == CLAIM_TBD for cell_id, backend in unresolved for mark in [spec.cell(cell_id).claimed[backend]])


def test_committed_probes_file_passes_the_json_schema() -> None:
    schema = json.loads((SUBTREE / "schemas" / "probes.schema.json").read_text(encoding="utf-8"))
    data = yaml.safe_load(PROBES.read_text(encoding="utf-8"))
    jsonschema.validate(data, schema)  # raises on violation


def test_human_only_cells_declare_no_probes() -> None:
    spec = load_probes_spec(PROBES)
    playground = spec.cell("playground")
    assert playground.classification == "human-only"
    assert playground.probes == []


# ---------------------------------------------------------------- error handling
def test_duplicate_probe_ids_are_rejected(tmp_path: Path) -> None:
    def mutate(data: dict[str, Any]) -> None:
        data["cells"][1]["probes"][0]["probe_id"] = data["cells"][0]["probes"][0]["probe_id"]

    with pytest.raises(RegistryError, match="duplicate probe_id"):
        load_probes_spec(_write_spec(tmp_path, mutate))


def test_claims_must_cover_every_backend(tmp_path: Path) -> None:
    def mutate(data: dict[str, Any]) -> None:
        del data["cells"][0]["claimed"]["opik"]

    with pytest.raises(RegistryError, match="claimed marks must cover"):
        load_probes_spec(_write_spec(tmp_path, mutate))


def test_human_only_cell_with_probes_is_rejected(tmp_path: Path) -> None:
    def mutate(data: dict[str, Any]) -> None:
        data["cells"][0]["classification"] = "human-only"

    with pytest.raises(RegistryError, match="must not declare probes"):
        load_probes_spec(_write_spec(tmp_path, mutate))


def test_control_backends_must_be_declared(tmp_path: Path) -> None:
    def mutate(data: dict[str, Any]) -> None:
        data["controls"]["synthetic"][0]["applies_to"] = ["mlflow"]

    with pytest.raises(RegistryError, match="unknown backends"):
        load_probes_spec(_write_spec(tmp_path, mutate))


def test_marks_table_must_match_package_constants(tmp_path: Path) -> None:
    def mutate(data: dict[str, Any]) -> None:
        data["marks"]["full"] = "X"

    with pytest.raises(RegistryError, match="marks must be exactly"):
        load_probes_spec(_write_spec(tmp_path, mutate))


def test_loader_error_paths(tmp_path: Path) -> None:
    with pytest.raises(RegistryError, match="cannot read"):
        load_probes_spec(tmp_path / "missing.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("cells: [unclosed", encoding="utf-8")
    with pytest.raises(RegistryError, match="not valid YAML"):
        load_probes_spec(bad)
    scalar = tmp_path / "scalar.yaml"
    scalar.write_text("42\n", encoding="utf-8")
    with pytest.raises(RegistryError, match="mapping at the top level"):
        load_probes_spec(scalar)
    duplicate_cell = _write_spec(tmp_path, lambda data: data["cells"].append(data["cells"][0]))
    with pytest.raises(RegistryError, match="duplicate"):
        load_probes_spec(duplicate_cell)


def test_unknown_cell_lookup_is_an_error() -> None:
    spec = load_probes_spec(PROBES)
    with pytest.raises(RegistryError, match="unknown cell id"):
        spec.cell("nope")


# --------------------------------------------------------------------- registry
def test_register_and_duplicate_registration() -> None:
    probe_id = "l1.test.only_for_registry_test"

    @register(probe_id)
    def _probe() -> None:  # pragma: no cover - never called
        raise AssertionError

    assert probe_id in registered_probe_ids()
    with pytest.raises(RegistryError, match="registered twice"):
        register(probe_id)(_probe)


def test_cross_validate_reports_both_directions() -> None:
    spec = load_probes_spec(PROBES)
    declared = spec.declared_probe_ids()
    problems = cross_validate(spec, declared)  # exactly the declared set -> clean
    assert problems == []
    missing_impl = cross_validate(spec, declared - {"l1.tracing.roundtrip"})
    assert any("not implemented: l1.tracing.roundtrip" in problem for problem in missing_impl)
    extra_impl = cross_validate(spec, declared | {"l1.ghost.probe"})
    assert any("not declared" in problem for problem in extra_impl)


def test_probe_id_shape_and_bad_claim_fail_validation(tmp_path: Path) -> None:
    with pytest.raises(RegistryError, match="failed validation"):
        load_probes_spec(_write_spec(tmp_path, lambda d: d["cells"][0]["probes"][0].__setitem__("probe_id", "bad id")))
    with pytest.raises(RegistryError, match="failed validation"):
        load_probes_spec(_write_spec(tmp_path, lambda d: d["cells"][0]["claimed"].__setitem__("langfuse", "X")))


def test_expectation_must_cover_every_backend(tmp_path: Path) -> None:
    def mutate(data: Any) -> None:
        del data["cells"][0]["probes"][0]["expectation"]["opik"]

    with pytest.raises(RegistryError, match="expectation must cover"):
        load_probes_spec(_write_spec(tmp_path, mutate))


def test_get_probe_without_implementation_is_an_error() -> None:
    with pytest.raises(RegistryError, match="no registered implementation"):
        get_probe("l1.never.registered")
