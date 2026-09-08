#!/usr/bin/env python3
"""Generate presentation-grade evaluation metric comparison charts.

Reads metric datasets conforming to ``docs/eval_metrics_schema.json`` and
renders high-resolution grouped bar charts and vector graphics comparing
evaluation platforms across target use cases and operational dimensions.

Zero hardcoded metrics or dimensions: all visual layout parameters are
derived dynamically from the input dataset.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger("generate_eval_metrics")

DEFAULT_INPUT_PATH = Path("docs/eval_metrics.json")
DEFAULT_OUTPUT_PATH = Path("docs/eval_metrics_comparison.png")
DEFAULT_DPI = 300

# Harmonious, accessible palette for executive slide presentations
DEFAULT_TOOL_COLORS = {
    "langfuse": "#2563EB",  # Royal Blue
    "phoenix": "#EA580C",  # Vibrant Deep Orange
    "braintrust": "#059669",  # Emerald Green
}
FALLBACK_COLORS = ["#7C3AED", "#DB2777", "#0891B2", "#4F46E5"]


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def _validate_schema_draft7(data: dict[str, Any], schema_path: Path) -> None:
    """Validate JSON data against Draft-07 schema if jsonschema is available."""
    if not schema_path.exists():
        return
    try:
        import jsonschema

        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.validate(instance=data, schema=schema)
    except ImportError:
        logger.debug("jsonschema not installed, falling back to manual structural checks")
    except Exception as exc:
        raise ValueError(f"Schema validation failed against {schema_path}: {exc}") from exc


def _validate_score_matrix(data: dict[str, Any]) -> None:
    """Ensure all required matrix entries exist and contain valid numeric scores."""
    tools: list[str] = data["tools"]
    dimensions: list[dict[str, Any]] = data["dimensions"]
    scores: dict[str, dict[str, Any]] = data["scores"]
    tool_profiles: dict[str, Any] = data.get("tool_profiles", {})
    dim_keys = [d["key"] for d in dimensions]

    for tool_key in tools:
        if tool_key not in tool_profiles:
            raise KeyError(f"Tool '{tool_key}' listed in 'tools' but missing from 'tool_profiles'")
        if tool_key not in scores:
            raise KeyError(f"Tool '{tool_key}' missing from 'scores'")
        for d_key in dim_keys:
            if d_key not in scores[tool_key]:
                raise ValueError(f"Missing score for tool '{tool_key}' on dimension '{d_key}'")
            score_entry = scores[tool_key][d_key]
            if not isinstance(score_entry, dict) or "score" not in score_entry or score_entry["score"] is None:
                raise ValueError(f"Invalid or missing score value for tool '{tool_key}' on dimension '{d_key}'")


def load_and_validate_metrics(input_path: Path, schema_path: Path | None = None) -> dict[str, Any]:
    """Load and validate the metrics JSON dataset against its Draft-07 schema and structural rules."""
    if not input_path.exists():
        raise FileNotFoundError(f"Metrics dataset not found: {input_path}")

    with input_path.open("r", encoding="utf-8") as f:
        try:
            raw_data = json.load(f)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Corrupted or invalid JSON in {input_path}: {exc}") from exc

    if not isinstance(raw_data, dict):
        raise TypeError(f"Metrics dataset must be a JSON object, got {type(raw_data).__name__}")
    data: dict[str, Any] = raw_data

    resolved_schema_path = schema_path or (input_path.parent / "eval_metrics_schema.json")
    _validate_schema_draft7(data, resolved_schema_path)

    required_keys = ["metadata", "use_cases", "tools", "dimensions", "tool_profiles", "scores"]
    for key in required_keys:
        if key not in data:
            raise KeyError(f"Missing required key '{key}' in {input_path}")

    _validate_score_matrix(data)
    return data


def render_comparison_chart(
    data: dict[str, Any],
    output_path: Path,
    output_format: str = "png",
    dpi: int = DEFAULT_DPI,
) -> list[Path]:
    """Render and save the grouped bar chart comparison."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        matplotlib.rcParams["svg.hashsalt"] = "eval_metrics_salt"
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError as exc:
        raise RuntimeError(
            "Rendering evaluation comparison charts requires 'matplotlib' and 'numpy'. "
            "Please install them via `pip install matplotlib numpy`."
        ) from exc

    tools: list[str] = data["tools"]
    dimensions: list[dict[str, Any]] = data["dimensions"]
    scores: dict[str, dict[str, Any]] = data["scores"]
    tool_profiles: dict[str, Any] = data.get("tool_profiles", {})

    dim_keys = [d["key"] for d in dimensions]
    dim_labels = [d["label"] for d in dimensions]
    num_dims = len(dimensions)
    num_tools = len(tools)

    # Compute bar positions
    x_indices = np.arange(num_dims)
    bar_width = 0.8 / max(num_tools, 1)

    fig, ax = plt.subplots(figsize=(14, 8), dpi=dpi)

    # Plot each tool
    for idx, tool_key in enumerate(tools):
        tool_scores = []
        for d in dim_keys:
            score_entry = scores.get(tool_key, {}).get(d)
            if score_entry is None or "score" not in score_entry:
                raise ValueError(f"Missing score for tool '{tool_key}' on dimension '{d}'")
            tool_scores.append(float(score_entry["score"]))

        display_name = tool_profiles.get(tool_key, {}).get("display_name", tool_key.capitalize())
        color = DEFAULT_TOOL_COLORS.get(tool_key, FALLBACK_COLORS[idx % len(FALLBACK_COLORS)])
        offset = (idx - (num_tools - 1) / 2) * bar_width
        bars = ax.bar(
            x_indices + offset,
            tool_scores,
            bar_width * 0.92,
            label=display_name,
            color=color,
            edgecolor="none",
            alpha=0.92,
        )

        # Value labels on top of each bar
        for bar in bars:
            height = bar.get_height()
            if height > 0:
                ax.annotate(
                    f"{height:.1f}",
                    xy=(bar.get_x() + bar.get_width() / 2, height),
                    xytext=(0, 4),
                    textcoords="offset points",
                    ha="center",
                    va="bottom",
                    fontsize=9,
                    fontweight="bold",
                    color="#334155",
                )

    # Dynamic scaling based on max_score of declared dimensions
    max_val = max((float(d.get("max_score", 10.0)) for d in dimensions), default=10.0)
    y_limit = max(max_val * 1.15, 1.0)

    # Formatting and styling
    scale_label = f"0 – {int(max_val) if max_val.is_integer() else max_val:.1f}"
    ax.set_ylabel(f"Score ({scale_label} scale)", fontsize=12, fontweight="bold", color="#1E293B", labelpad=10)
    ax.set_title(
        f"{data['metadata'].get('title', 'Evaluation Tools Benchmark')}\n"
        "Comparative Analysis: Test Case Gen, Root Cause Analysis & Requirement Gen",
        fontsize=15,
        fontweight="bold",
        color="#0F172A",
        pad=18,
    )
    ax.set_xticks(x_indices)
    ax.set_xticklabels(dim_labels, fontsize=11, fontweight="semibold", color="#334155")
    ax.set_ylim(0, y_limit)
    ax.yaxis.grid(True, linestyle="--", alpha=0.5, color="#CBD5E1")
    ax.set_axisbelow(True)

    # Clean borders
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#94A3B8")
    ax.spines["bottom"].set_color("#94A3B8")

    # Legend
    legend = ax.legend(
        loc="upper left",
        bbox_to_anchor=(0.02, 0.98),
        frameon=True,
        facecolor="#FFFFFF",
        edgecolor="#E2E8F0",
        framealpha=0.95,
        fontsize=11,
    )
    legend.get_frame().set_linewidth(1.0)

    # Subtitle note on bottom left
    footer_text = f"Source: {data['metadata'].get('data_source_policy', 'Repository E2E & Matrix Coverage')} (v{data['metadata'].get('version', '1.0.0')})"
    fig.text(0.12, 0.02, footer_text, fontsize=8.5, color="#64748B", style="italic")

    plt.tight_layout(rect=(0, 0.04, 1, 1))

    # Output file paths
    saved_paths: list[Path] = []
    parent_dir = output_path.parent
    parent_dir.mkdir(parents=True, exist_ok=True)
    stem = output_path.stem

    if output_format in ("png", "both"):
        png_path = parent_dir / f"{stem}.png"
        fig.savefig(png_path, dpi=dpi, bbox_inches="tight")
        saved_paths.append(png_path)
        logger.info("Generated PNG chart: %s", png_path)

    if output_format in ("svg", "both"):
        svg_path = parent_dir / f"{stem}.svg"
        fig.savefig(svg_path, format="svg", bbox_inches="tight", metadata={"Date": None})
        saved_paths.append(svg_path)
        logger.info("Generated SVG vector chart: %s", svg_path)

    plt.close(fig)
    return saved_paths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--input",
        "-i",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help=f"Path to input JSON metrics dataset (default: {DEFAULT_INPUT_PATH})",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"Path to output image file (default: {DEFAULT_OUTPUT_PATH})",
    )
    parser.add_argument(
        "--format",
        "-f",
        choices=["png", "svg", "both"],
        default="both",
        help="Export format: png, svg, or both (default: both)",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=DEFAULT_DPI,
        help=f"Chart resolution in DPI (default: {DEFAULT_DPI})",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Dry run validation: verifies dataset schema integrity and visual asset freshness.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.log_level)

    try:
        data = load_and_validate_metrics(args.input)
        logger.info(
            "Validated metrics dataset '%s' with %d tools and %d dimensions",
            args.input,
            len(data.get("tools", [])),
            len(data.get("dimensions", [])),
        )

        if args.check:
            # Verify that committed visual assets exist and are non-empty
            parent_dir = args.output.parent
            stem = args.output.stem
            png_target = parent_dir / f"{stem}.png"
            svg_target = parent_dir / f"{stem}.svg"

            if args.format in ("png", "both") and (not png_target.exists() or png_target.stat().st_size == 0):
                logger.error("Check mode failed: missing or empty PNG asset '%s'", png_target)
                return 1
            if args.format in ("svg", "both") and (not svg_target.exists() or svg_target.stat().st_size == 0):
                logger.error("Check mode failed: missing or empty SVG asset '%s'", svg_target)
                return 1

            # When rendering libraries are installed, verify that SVG asset is fresh
            try:
                import matplotlib  # noqa: F401
                import numpy  # noqa: F401

                with tempfile.TemporaryDirectory() as tmp_dir:
                    tmp_out = Path(tmp_dir) / f"{stem}.svg"
                    render_comparison_chart(data, output_path=tmp_out, output_format="svg", dpi=args.dpi)
                    tmp_svg = Path(tmp_dir) / f"{stem}.svg"
                    if tmp_svg.read_bytes() != svg_target.read_bytes():
                        logger.error(
                            "Check mode failed: committed SVG asset '%s' is stale. "
                            "Run `python scripts/generate_eval_metrics.py` to regenerate.",
                            svg_target,
                        )
                        return 1
            except (ImportError, RuntimeError):
                logger.info("Visual rendering libraries not present; verified schema and asset existence.")

            logger.info("Check mode: dataset integrity and visual assets verified successfully.")
            return 0

        saved = render_comparison_chart(
            data,
            output_path=args.output,
            output_format=args.format,
            dpi=args.dpi,
        )
        logger.info("Successfully exported %d visual assets.", len(saved))
        return 0

    except Exception as exc:
        logger.error("Chart generation failed: %s", exc, exc_info=args.log_level == "DEBUG")
        return 1


if __name__ == "__main__":
    sys.exit(main())
