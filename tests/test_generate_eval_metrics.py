"""Unit tests for scripts/generate_eval_metrics.py.

Verifies schema loading, validation error paths, chart generation,
and CLI interface modes without hardcoded assumptions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from generate_eval_metrics import (
    DEFAULT_INPUT_PATH,
    build_parser,
    load_and_validate_metrics,
    main,
    render_comparison_chart,
)


@pytest.fixture
def minimal_metrics_data() -> dict[str, Any]:
    return {
        "metadata": {
            "title": "Test Benchmark",
            "version": "0.1.0",
            "generated_date": "2026-09-07",
            "data_source_policy": "Test Fixture",
        },
        "use_cases": {
            "test_case_gen": {
                "name": "Test Gen",
                "description": "Desc",
                "key_metrics": ["m1"],
                "matrix_reference": "ref",
            }
        },
        "tools": ["tool_a", "tool_b"],
        "dimensions": [
            {
                "key": "dim_1",
                "label": "Dimension 1",
                "category": "use_case",
                "max_score": 10.0,
                "description": "Dim 1 Desc",
            }
        ],
        "tool_profiles": {
            "tool_a": {
                "display_name": "Tool A",
                "licensing": "MIT",
                "deployment_model": "Self-hosted",
                "airgap_capable": True,
                "telemetry_protocol": "OTLP",
                "matrix_components": {},
            },
            "tool_b": {
                "display_name": "Tool B",
                "licensing": "Proprietary",
                "deployment_model": "Cloud",
                "airgap_capable": False,
                "telemetry_protocol": "REST",
                "matrix_components": {},
            },
        },
        "scores": {
            "tool_a": {
                "dim_1": {
                    "score": 8.5,
                    "rationale": "High score",
                    "evidence_ref": "ref_a",
                }
            },
            "tool_b": {
                "dim_1": {
                    "score": 6.0,
                    "rationale": "Moderate score",
                    "evidence_ref": "ref_b",
                }
            },
        },
    }


def test_load_and_validate_metrics_valid(tmp_path: Path, minimal_metrics_data: dict[str, Any]) -> None:
    data_file = tmp_path / "valid_metrics.json"
    with data_file.open("w", encoding="utf-8") as f:
        json.dump(minimal_metrics_data, f)

    loaded = load_and_validate_metrics(data_file)
    assert loaded["metadata"]["title"] == "Test Benchmark"
    assert loaded["tools"] == ["tool_a", "tool_b"]


def test_load_and_validate_metrics_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "non_existent.json"
    with pytest.raises(FileNotFoundError, match="Metrics dataset not found"):
        load_and_validate_metrics(missing)


def test_load_and_validate_metrics_corrupt_json(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{ unclosed json: ", encoding="utf-8")
    with pytest.raises(ValueError, match="Corrupted or invalid JSON"):
        load_and_validate_metrics(corrupt)


def test_load_and_validate_metrics_missing_keys(tmp_path: Path) -> None:
    incomplete = tmp_path / "incomplete.json"
    incomplete.write_text('{"metadata": {}}', encoding="utf-8")
    with pytest.raises(KeyError, match="Missing required key"):
        load_and_validate_metrics(incomplete)


def test_render_comparison_chart(tmp_path: Path, minimal_metrics_data: dict[str, Any]) -> None:
    pytest.importorskip("matplotlib", reason="matplotlib required for rendering comparison charts")
    out_png = tmp_path / "chart.png"
    saved = render_comparison_chart(minimal_metrics_data, output_path=out_png, output_format="both", dpi=100)

    assert len(saved) == 2
    png_path = tmp_path / "chart.png"
    svg_path = tmp_path / "chart.svg"
    assert png_path.exists()
    assert png_path.stat().st_size > 0
    assert svg_path.exists()
    assert svg_path.stat().st_size > 0


def test_render_comparison_chart_missing_dependencies(
    monkeypatch: pytest.MonkeyPatch, minimal_metrics_data: dict[str, Any], tmp_path: Path
) -> None:
    """Verify informative error when matplotlib is missing at render time."""
    import sys

    monkeypatch.setitem(sys.modules, "matplotlib", None)
    out_png = tmp_path / "chart.png"
    with pytest.raises(RuntimeError, match="requires 'matplotlib' and 'numpy'"):
        render_comparison_chart(minimal_metrics_data, output_path=out_png)


def test_load_and_validate_metrics_schema_invalid_nested_score(
    tmp_path: Path, minimal_metrics_data: dict[str, Any]
) -> None:
    """Verify that an invalid score (>10.0) fails jsonschema validation."""
    data = json.loads(json.dumps(minimal_metrics_data))
    data["scores"]["tool_a"]["dim_1"]["score"] = 15.0  # Max is 10.0 in schema
    data_file = tmp_path / "invalid_score.json"
    data_file.write_text(json.dumps(data), encoding="utf-8")

    schema_file = Path("docs/eval_metrics_schema.json")
    with pytest.raises(ValueError, match="Schema validation failed"):
        load_and_validate_metrics(data_file, schema_path=schema_file)


def test_load_and_validate_metrics_missing_use_cases(tmp_path: Path, minimal_metrics_data: dict[str, Any]) -> None:
    """Verify that omitting the required use_cases key fails validation."""
    data = json.loads(json.dumps(minimal_metrics_data))
    del data["use_cases"]
    data_file = tmp_path / "missing_use_cases.json"
    data_file.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises((KeyError, ValueError)):
        load_and_validate_metrics(data_file)


def test_load_and_validate_metrics_missing_dimension_score(
    tmp_path: Path, minimal_metrics_data: dict[str, Any]
) -> None:
    """Verify that missing a dimension score for a tool fails closed."""
    data = json.loads(json.dumps(minimal_metrics_data))
    del data["scores"]["tool_a"]["dim_1"]
    data_file = tmp_path / "missing_score.json"
    data_file.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="Missing score for tool 'tool_a'"):
        load_and_validate_metrics(data_file)


def test_main_check_mode(tmp_path: Path, minimal_metrics_data: dict[str, Any]) -> None:
    pytest.importorskip("matplotlib")
    data_file = tmp_path / "metrics.json"
    with data_file.open("w", encoding="utf-8") as f:
        json.dump(minimal_metrics_data, f)

    out_file = tmp_path / "chart.png"
    # First generate the assets so they exist
    main(["--input", str(data_file), "--output", str(out_file), "--format", "both", "--dpi", "100"])

    # Now verify --check passes
    exit_code = main(
        ["--input", str(data_file), "--output", str(out_file), "--format", "both", "--check", "--dpi", "100"]
    )
    assert exit_code == 0


def test_main_check_mode_without_matplotlib(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, minimal_metrics_data: dict[str, Any]
) -> None:
    """Verify that --check succeeds when assets exist even if matplotlib is not installed."""
    import sys

    monkeypatch.setitem(sys.modules, "matplotlib", None)
    data_file = tmp_path / "metrics.json"
    data_file.write_text(json.dumps(minimal_metrics_data), encoding="utf-8")

    out_file = tmp_path / "chart.png"
    svg_file = tmp_path / "chart.svg"
    out_file.write_text("dummy png bytes", encoding="utf-8")
    svg_file.write_text("<svg>dummy</svg>", encoding="utf-8")

    exit_code = main(["--input", str(data_file), "--output", str(out_file), "--format", "both", "--check"])
    assert exit_code == 0


def test_main_check_mode_missing_asset(tmp_path: Path, minimal_metrics_data: dict[str, Any]) -> None:
    """Verify that --check fails if the expected chart assets are missing."""
    data_file = tmp_path / "metrics.json"
    with data_file.open("w", encoding="utf-8") as f:
        json.dump(minimal_metrics_data, f)

    out_file = tmp_path / "non_existent_chart.png"
    exit_code = main(["--input", str(data_file), "--output", str(out_file), "--check"])
    assert exit_code == 1


def test_main_check_mode_stale_asset(tmp_path: Path, minimal_metrics_data: dict[str, Any]) -> None:
    """Verify that --check fails if the committed SVG chart is stale compared to dataset."""
    pytest.importorskip("matplotlib")
    data_file = tmp_path / "metrics.json"
    with data_file.open("w", encoding="utf-8") as f:
        json.dump(minimal_metrics_data, f)

    out_file = tmp_path / "chart.png"
    # Generate original assets
    main(["--input", str(data_file), "--output", str(out_file), "--format", "both", "--dpi", "100"])

    # Stale the SVG by modifying file content
    svg_file = tmp_path / "chart.svg"
    svg_file.write_text("<svg>stale content</svg>", encoding="utf-8")

    # --check must catch this drift and fail with exit code 1
    exit_code = main(
        ["--input", str(data_file), "--output", str(out_file), "--format", "both", "--check", "--dpi", "100"]
    )
    assert exit_code == 1


def test_main_full_generation(tmp_path: Path, minimal_metrics_data: dict[str, Any]) -> None:
    pytest.importorskip("matplotlib", reason="matplotlib required for full chart generation")
    data_file = tmp_path / "metrics.json"
    out_file = tmp_path / "out_chart.png"
    with data_file.open("w", encoding="utf-8") as f:
        json.dump(minimal_metrics_data, f)

    exit_code = main(["--input", str(data_file), "--output", str(out_file), "--format", "png", "--dpi", "100"])
    assert exit_code == 0
    assert out_file.exists()
    assert out_file.stat().st_size > 0


def test_main_missing_file_error() -> None:
    exit_code = main(["--input", "non_existent_file_xyz.json"])
    assert exit_code == 1


def test_default_file_validation() -> None:
    """Verify that the repository's default metrics file passes validation."""
    if DEFAULT_INPUT_PATH.exists():
        data = load_and_validate_metrics(DEFAULT_INPUT_PATH)
        assert "langfuse" in data["tools"]
        assert "phoenix" in data["tools"]
        assert "braintrust" in data["tools"]


def test_build_parser() -> None:
    parser = build_parser()
    args = parser.parse_args(["--format", "svg", "--dpi", "200"])
    assert args.format == "svg"
    assert args.dpi == 200
