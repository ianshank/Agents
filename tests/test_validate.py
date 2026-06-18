#!/usr/bin/env python3
"""Tests for scripts/validate.py — harness enforcement script."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_schema(tmp: Path) -> Path:
    """Write the canonical features.schema.json to tmp and return the path."""
    schema_path = tmp / "features.schema.json"
    # Minimal schema matching the real one
    schema: dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "features.yaml",
        "type": "object",
        "required": ["features"],
        "properties": {
            "features": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "name", "category", "priority", "status", "verification", "depends_on"],
                    "properties": {
                        "id": {"type": "string", "pattern": "^([A-Z]+-)?F-[0-9]{3,}$"},
                        "epic": {"type": "string"},
                        "name": {"type": "string", "minLength": 1},
                        "description": {"type": "string"},
                        "category": {"enum": ["functional", "non-functional", "infrastructure", "validation"]},
                        "priority": {"enum": ["critical", "high", "medium", "low"]},
                        "status": {"enum": ["todo", "in_progress", "done", "blocked", "deferred"]},
                        "tier": {"enum": ["fast", "slow", "hardware"]},
                        "verification": {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1},
                        "validation_command": {"type": ["string", "null"]},
                        "implemented_in": {"type": ["string", "null"]},
                        "depends_on": {"type": "array", "items": {"type": "string"}},
                        "notes": {"type": "string"},
                    },
                    "allOf": [
                        {
                            "if": {"properties": {"status": {"const": "done"}}},
                            "then": {
                                "required": ["validation_command", "implemented_in"],
                                "properties": {"validation_command": {"type": "string", "minLength": 1}},
                            },
                        }
                    ],
                },
            }
        },
    }
    schema_path.write_text(json.dumps(schema, indent=2))
    return schema_path


def _write_features(tmp: Path, features: list[dict[str, Any]]) -> Path:
    """Write a features.yaml file and return its path."""
    feat_path = tmp / "features.yaml"
    feat_path.write_text(yaml.dump({"features": features}, default_flow_style=False))
    return feat_path


def _make_valid_feature(**overrides: Any) -> dict[str, Any]:
    """Return a minimal valid feature dict, with optional overrides."""
    base: dict[str, Any] = {
        "id": "F-001",
        "epic": "Test",
        "name": "Test feature",
        "description": "A test feature.",
        "category": "infrastructure",
        "priority": "critical",
        "status": "todo",
        "tier": "fast",
        "verification": ["Check something"],
        "validation_command": None,
        "implemented_in": None,
        "depends_on": [],
        "notes": "",
    }
    base.update(overrides)
    return base


def _run_validate(tmp: Path, extra_args: str = "") -> subprocess.CompletedProcess[str]:
    """Run validate.py against files in tmp."""
    validate_script = Path(__file__).resolve().parent.parent / "scripts" / "validate.py"
    cmd = (
        f"python {validate_script} "
        f"--features {tmp / 'features.yaml'} "
        f"--schema {tmp / 'features.schema.json'} "
        f"{extra_args}"
    )
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=str(tmp))


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


class TestSchemaValidation:
    """Tests for JSON schema enforcement of features.yaml."""

    def test_valid_feature_passes_schema(self, tmp_path: Path) -> None:
        _write_schema(tmp_path)
        _write_features(tmp_path, [_make_valid_feature()])
        result = _run_validate(tmp_path, "--tier fast")
        assert result.returncode == 0

    def test_missing_required_field_fails(self, tmp_path: Path) -> None:
        _write_schema(tmp_path)
        bad_feat = _make_valid_feature()
        del bad_feat["verification"]
        _write_features(tmp_path, [bad_feat])
        result = _run_validate(tmp_path, "--tier fast")
        assert result.returncode == 1
        assert "schema" in result.stdout.lower() or "verification" in result.stdout.lower()

    def test_invalid_enum_value_fails(self, tmp_path: Path) -> None:
        _write_schema(tmp_path)
        _write_features(tmp_path, [_make_valid_feature(priority="urgent")])
        result = _run_validate(tmp_path, "--tier fast")
        assert result.returncode == 1

    def test_empty_verification_fails(self, tmp_path: Path) -> None:
        _write_schema(tmp_path)
        _write_features(tmp_path, [_make_valid_feature(verification=[])])
        result = _run_validate(tmp_path, "--tier fast")
        assert result.returncode == 1


# ---------------------------------------------------------------------------
# DAG tests
# ---------------------------------------------------------------------------


class TestDAGValidation:
    """Tests for dependency graph integrity checks."""

    def test_cycle_detected(self, tmp_path: Path) -> None:
        _write_schema(tmp_path)
        feats = [
            _make_valid_feature(id="F-001", depends_on=["F-002"]),
            _make_valid_feature(id="F-002", depends_on=["F-001"]),
        ]
        _write_features(tmp_path, feats)
        result = _run_validate(tmp_path, "--tier fast")
        assert result.returncode == 1
        assert "cycle" in result.stdout.lower()

    def test_missing_dependency_edge(self, tmp_path: Path) -> None:
        _write_schema(tmp_path)
        feats = [_make_valid_feature(id="F-001", depends_on=["F-999"])]
        _write_features(tmp_path, feats)
        result = _run_validate(tmp_path, "--tier fast")
        assert result.returncode == 1
        assert "F-999" in result.stdout

    def test_valid_dag_passes(self, tmp_path: Path) -> None:
        _write_schema(tmp_path)
        feats = [
            _make_valid_feature(id="F-001", depends_on=[]),
            _make_valid_feature(id="F-002", depends_on=["F-001"]),
        ]
        _write_features(tmp_path, feats)
        result = _run_validate(tmp_path, "--tier fast")
        assert result.returncode == 0


# ---------------------------------------------------------------------------
# Tier filtering tests
# ---------------------------------------------------------------------------


class TestTierFiltering:
    """Tests for tier-based command execution filtering."""

    def test_fast_tier_skips_slow_features(self, tmp_path: Path) -> None:
        _write_schema(tmp_path)
        feats = [
            _make_valid_feature(
                id="F-001",
                status="done",
                tier="slow",
                validation_command="python -c \"print('slow')\"",
                implemented_in="abc123",
            ),
        ]
        _write_features(tmp_path, feats)
        result = _run_validate(tmp_path, "--tier fast")
        assert result.returncode == 0
        assert "skipped" in result.stdout.lower()


# ---------------------------------------------------------------------------
# Done feature validation tests
# ---------------------------------------------------------------------------


class TestDoneFeatureValidation:
    """Tests for validation_command execution on done features."""

    def test_done_feature_passing_command(self, tmp_path: Path) -> None:
        _write_schema(tmp_path)
        feats = [
            _make_valid_feature(
                id="F-001",
                status="done",
                tier="fast",
                validation_command='python -c "import sys; sys.exit(0)"',
                implemented_in="abc123",
            ),
        ]
        _write_features(tmp_path, feats)
        result = _run_validate(tmp_path, "--tier fast")
        assert result.returncode == 0

    def test_done_feature_failing_command(self, tmp_path: Path) -> None:
        _write_schema(tmp_path)
        feats = [
            _make_valid_feature(
                id="F-001",
                status="done",
                tier="fast",
                validation_command='python -c "import sys; sys.exit(1)"',
                implemented_in="abc123",
            ),
        ]
        _write_features(tmp_path, feats)
        result = _run_validate(tmp_path, "--tier fast")
        assert result.returncode == 1
        assert "failed" in result.stdout.lower()


# ---------------------------------------------------------------------------
# Single feature check tests
# ---------------------------------------------------------------------------


class TestSingleFeatureCheck:
    """Tests for --check F-XXX mode."""

    def test_check_existing_feature(self, tmp_path: Path) -> None:
        _write_schema(tmp_path)
        feats = [
            _make_valid_feature(
                id="F-001",
                status="done",
                tier="fast",
                validation_command="python -c \"print('ok')\"",
                implemented_in="abc123",
            ),
        ]
        _write_features(tmp_path, feats)
        result = _run_validate(tmp_path, "--check F-001")
        assert result.returncode == 0
        assert "OK" in result.stdout

    def test_check_unknown_feature(self, tmp_path: Path) -> None:
        _write_schema(tmp_path)
        _write_features(tmp_path, [_make_valid_feature()])
        result = _run_validate(tmp_path, "--check F-999")
        assert result.returncode == 1
        assert "unknown" in result.stdout.lower() or "F-999" in result.stdout
