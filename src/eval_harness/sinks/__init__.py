"""Built-in result sinks."""

from __future__ import annotations

import html as _html
import json
import logging
from pathlib import Path

from ..braintrust_client import BrainTrustClient, NullBrainTrustClient, build_client
from ..core._serialize import as_text as _as_text
from ..core.interfaces import ResultSink
from ..core.types import RunResult
from ..langfuse_client import LangfuseClient
from ..phoenix_client import PhoenixScoreClient, build_score_client
from ..plugins import SINKS

logger = logging.getLogger(__name__)


@SINKS.register("console")
class ConsoleSink(ResultSink):
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.lines: list[str] = []

    def emit(self, run: RunResult) -> None:
        self.lines = [f"run '{run.run_id}' — {len(run.items)} item(s)"]
        for name, agg in run.aggregate.items():
            pr = "n/a" if agg.pass_rate is None else f"{agg.pass_rate:.2f}"
            self.lines.append(f"  {name}: mean={agg.mean:.3f} pass_rate={pr} n={agg.count}")
        if self.verbose:
            for ir in run.items:
                self.lines.append(f"  - {ir.item.id}: {[(s.name, round(s.value, 3)) for s in ir.scores]}")
        print("\n".join(self.lines))


@SINKS.register("json_file", aliases=("json",))
class JsonFileSink(ResultSink):
    def __init__(self, path: str, indent: int = 2):
        self.path = Path(path)
        self.indent = indent

    def emit(self, run: RunResult) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(run.to_dict(), indent=self.indent, default=str))


@SINKS.register("html_file", aliases=("html",))
class HtmlFileSink(ResultSink):
    """Renders a ``RunResult`` to a single self-contained HTML report.

    The output is dependency-free (inline CSS + inline SVG, no external assets or
    CDN links) and is a pure function of the ``RunResult`` — the same run renders
    byte-identically. ``bar_width_px`` is the only presentation tunable; nothing
    in the layout is otherwise hardcoded against the data.
    """

    #: SVG bar geometry — presentation constants, not behavioural thresholds.
    _DEFAULT_BAR_WIDTH_PX = 280
    _BAR_HEIGHT_PX = 14

    #: Palette — presentation constants (GitHub-light-friendly), single-sourced
    #: here rather than scattered as inline literals across the CSS/SVG builders.
    _COLOR_TEXT = "#1b1b1b"
    _COLOR_BORDER = "#d0d7de"
    _COLOR_HEADER_BG = "#f6f8fa"
    _COLOR_BAR_BG = "#eaeef2"
    _COLOR_BAR_FILL = "#2da44e"

    def __init__(
        self,
        path: str,
        title: str | None = None,
        embed_items: bool = True,
        bar_width_px: int = _DEFAULT_BAR_WIDTH_PX,
    ):
        self.path = Path(path)
        self.title = title
        self.embed_items = embed_items
        self.bar_width_px = bar_width_px

    def emit(self, run: RunResult) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(self.render(run), encoding="utf-8")

    # -- rendering (pure; deterministic for a fixed RunResult) -----------------
    def render(self, run: RunResult) -> str:
        title = self.title or f"Eval Report — {run.config_name}"
        sections = [
            self._head(title),
            self._summary(run),
            self._aggregate_table(run),
        ]
        if self.embed_items:
            sections.append(self._items_table(run))
        sections.append("</body></html>")
        return "\n".join(sections)

    def _head(self, title: str) -> str:
        esc = _html.escape(title)
        return (
            "<!DOCTYPE html>\n"
            '<html lang="en"><head><meta charset="utf-8">'
            f"<title>{esc}</title>"
            "<style>"
            f"body{{font-family:system-ui,sans-serif;margin:2rem;color:{self._COLOR_TEXT}}}"
            "h1{font-size:1.4rem}table{border-collapse:collapse;margin:1rem 0}"
            f"th,td{{border:1px solid {self._COLOR_BORDER};padding:4px 10px;text-align:left;font-size:0.9rem}}"
            f"th{{background:{self._COLOR_HEADER_BG}}}.metric-bar{{vertical-align:middle}}"
            "caption{caption-side:top;text-align:left;font-weight:600;margin-bottom:4px}"
            "</style></head><body>"
            f"<h1>{esc}</h1>"
        )

    def _summary(self, run: RunResult) -> str:
        return (
            "<table><caption>Run</caption>"
            f"<tr><th>run_id</th><td>{_html.escape(run.run_id)}</td></tr>"
            f"<tr><th>config</th><td>{_html.escape(run.config_name)}</td></tr>"
            f"<tr><th>items</th><td>{len(run.items)}</td></tr>"
            f"<tr><th>started_at</th><td>{_html.escape(run.started_at.isoformat())}</td></tr>"
            f"<tr><th>finished_at</th><td>{_html.escape(run.finished_at.isoformat())}</td></tr>"
            "</table>"
        )

    def _bar(self, value: float) -> str:
        """An inline-SVG horizontal bar for a value in [0, 1] (clamped)."""
        frac = 0.0 if value < 0 else 1.0 if value > 1 else value
        fill = self.bar_width_px * frac
        return (
            f'<svg class="metric-bar" width="{self.bar_width_px}" height="{self._BAR_HEIGHT_PX}" '
            f'viewBox="0 0 {self.bar_width_px} {self._BAR_HEIGHT_PX}" '
            'xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
            f'<rect width="{self.bar_width_px}" height="{self._BAR_HEIGHT_PX}" fill="{self._COLOR_BAR_BG}"/>'
            f'<rect width="{fill:.2f}" height="{self._BAR_HEIGHT_PX}" fill="{self._COLOR_BAR_FILL}"/></svg>'
        )

    def _aggregate_table(self, run: RunResult) -> str:
        rows = [
            "<table><caption>Scores</caption><tr><th>score</th><th>mean</th><th></th><th>pass_rate</th><th>n</th></tr>"
        ]
        for name, agg in sorted(run.aggregate.items()):
            pr = "n/a" if agg.pass_rate is None else f"{agg.pass_rate:.3f}"
            rows.append(
                f"<tr><td>{_html.escape(name)}</td>"
                f"<td>{agg.mean:.3f}</td><td>{self._bar(agg.mean)}</td>"
                f"<td>{pr}</td><td>{agg.count}</td></tr>"
            )
        rows.append("</table>")
        return "".join(rows)

    def _items_table(self, run: RunResult) -> str:
        rows = ["<table><caption>Items</caption><tr><th>id</th><th>output</th><th>scores</th></tr>"]
        for ir in run.items:
            scores = ", ".join(f"{_html.escape(s.name)}={s.value:.3f}" for s in ir.scores)
            output = _html.escape(_as_text(ir.output.output))
            rows.append(f"<tr><td>{_html.escape(ir.item.id)}</td><td>{output}</td><td>{scores}</td></tr>")
        rows.append("</table>")
        return "".join(rows)


@SINKS.register("langfuse")
class LangfuseSink(ResultSink):
    """Writes per-item scores back to Langfuse. Client injected by the engine."""

    def __init__(self, min_value_to_log: float | None = None):
        self.min_value_to_log = min_value_to_log
        self._client: LangfuseClient | None = None

    def attach_client(self, client: LangfuseClient) -> None:
        self._client = client

    def emit(self, run: RunResult) -> None:
        if self._client is None:
            raise RuntimeError("LangfuseSink has no client attached")
        for ir in run.items:
            for s in ir.scores:
                if self.min_value_to_log is not None and s.value < self.min_value_to_log:
                    continue
                self._client.log_score(
                    run_id=run.run_id,
                    item_id=ir.item.id,
                    name=s.name,
                    value=s.value,
                    comment=s.comment,
                )
        self._client.flush()


@SINKS.register("phoenix")
class PhoenixSink(ResultSink):
    """Exports per-item eval scores to a self-hosted Phoenix as OpenTelemetry spans.

    Additive and reversible: it self-constructs its own narrow score client (a no-op
    unless ``enabled`` *and* the Phoenix SDK is installed), so — unlike ``LangfuseSink``
    — it needs no engine injection and cannot be cross-wired with the Langfuse client by
    the engine's generic ``attach_client`` loop. The score loop mirrors ``LangfuseSink``.
    """

    def __init__(self, enabled: bool = False, min_value_to_log: float | None = None):
        self.min_value_to_log = min_value_to_log
        self._client: PhoenixScoreClient = build_score_client(enabled=enabled)

    def emit(self, run: RunResult) -> None:
        for ir in run.items:
            for s in ir.scores:
                if self.min_value_to_log is not None and s.value < self.min_value_to_log:
                    continue
                self._client.log_score(
                    run_id=run.run_id,
                    item_id=ir.item.id,
                    name=s.name,
                    value=s.value,
                    comment=s.comment,
                )
        self._client.flush()


@SINKS.register("braintrust")
class BrainTrustSink(ResultSink):
    """Exports each eval item to a BrainTrust *experiment* via the native ``experiment.log``.

    Additive and reversible: like ``PhoenixSink`` it self-constructs its own narrow client
    (a no-op unless ``enabled`` *and* the ``braintrust`` SDK is installed), so it needs no
    engine injection and cannot be cross-wired with the Langfuse client by the engine's
    generic ``attach_client`` loop. Unlike the per-score Phoenix/Langfuse sinks, BrainTrust's
    write-path is per *item*: each item logs one row carrying ``input``/``output``/``expected``
    plus a ``{name: value}`` ``scores`` dict. The client is built in ``emit`` (not ``__init__``)
    because the BrainTrust experiment is named after the run.

    ``min_value_to_log`` filters which scores are attached to the row (the item is still logged,
    preserving its input/output), mirroring the threshold semantics of the other sinks.
    """

    def __init__(
        self,
        enabled: bool = False,
        project_name: str = "eval-harness",
        min_value_to_log: float | None = None,
    ):
        self.enabled = enabled
        self.project_name = project_name
        self.min_value_to_log = min_value_to_log
        # Placeholder until emit() builds the run-scoped client; keeps the attribute typed
        # and lets the sink be constructed/inspected offline without the SDK.
        self._client: BrainTrustClient = NullBrainTrustClient()

    def emit(self, run: RunResult) -> None:
        self._client = build_client(
            enabled=self.enabled,
            project_name=self.project_name,
            experiment_name=run.run_id,
        )
        for ir in run.items:
            scores = {
                s.name: s.value for s in ir.scores if self.min_value_to_log is None or s.value >= self.min_value_to_log
            }
            self._client.log_item(
                run_id=run.run_id,
                item_id=ir.item.id,
                input=ir.item.inputs,
                output=ir.output.output,
                expected=ir.item.expected,
                scores=scores,
                metadata={"config_name": run.config_name},
            )
        self._client.flush()
        if self.enabled:
            logger.info("BrainTrust sink: exported %d item(s) to experiment %s", len(run.items), run.run_id)
        else:
            logger.debug("BrainTrust sink disabled; %d item(s) not exported (no-op)", len(run.items))
