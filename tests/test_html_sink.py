from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from eval_harness.core.types import (
    EvalItem,
    ItemResult,
    RunResult,
    ScoreAggregate,
    ScoreResult,
    TargetOutput,
)
from eval_harness.plugins import SINKS

_EXTERNAL_RESOURCE = re.compile(r"""(<script[^>]*\ssrc=|<link[^>]*\shref=|@import|url\(\s*['"]?https?:)""", re.I)

_TS = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _run(items=None, aggregate=None):
    if items is None:
        items = [
            ItemResult(
                item=EvalItem(id="i1", inputs={"q": "hi"}, expected="x"),
                output=TargetOutput(output="hello"),
                scores=[ScoreResult("accuracy", value=1.0, passed=True)],
            )
        ]
    if aggregate is None:
        aggregate = {"accuracy": ScoreAggregate(count=1, mean=1.0, pass_rate=1.0)}
    return RunResult(
        run_id="run-1",
        config_name="demo",
        items=items,
        aggregate=aggregate,
        started_at=_TS,
        finished_at=_TS,
    )


def test_registered_with_alias():
    assert "html_file" in SINKS
    assert "html" in SINKS
    assert SINKS.resolve("html") == "html_file"


def test_emit_writes_file_with_core_content(tmp_path: Path):
    out = tmp_path / "report.html"
    sink = SINKS.create("html_file", {"path": str(out)})
    sink.emit(_run())
    text = out.read_text(encoding="utf-8")
    assert "<html" in text.lower()
    assert "run-1" in text
    assert "accuracy" in text
    assert "1.000" in text  # mean formatted


def test_nested_parent_dir_created(tmp_path: Path):
    out = tmp_path / "a" / "b" / "report.html"
    SINKS.create("html_file", {"path": str(out)}).emit(_run())
    assert out.exists()


def test_self_contained_no_external_resources(tmp_path: Path):
    out = tmp_path / "report.html"
    SINKS.create("html_file", {"path": str(out)}).emit(_run())
    text = out.read_text(encoding="utf-8")
    assert _EXTERNAL_RESOURCE.search(text) is None
    # the SVG namespace URI is present and must NOT be treated as external
    assert "http://www.w3.org/2000/svg" in text


def test_deterministic_render(tmp_path: Path):
    sink = SINKS.create("html_file", {"path": str(tmp_path / "r.html")})
    run = _run()
    assert sink.render(run) == sink.render(run)


def test_pass_rate_none_renders_na(tmp_path: Path):
    run = _run(aggregate={"latency": ScoreAggregate(count=1, mean=0.5, pass_rate=None)})
    text = SINKS.create("html_file", {"path": str(tmp_path / "r.html")}).render(run)
    assert "n/a" in text


def test_embed_items_false_skips_item_table(tmp_path: Path):
    run = _run()
    with_items = SINKS.create("html_file", {"path": str(tmp_path / "a.html")}).render(run)
    without = SINKS.create("html_file", {"path": str(tmp_path / "b.html"), "embed_items": False}).render(run)
    assert "Items" in with_items
    assert "Items" not in without


def test_empty_run_renders_valid_html(tmp_path: Path):
    run = _run(items=[], aggregate={})
    text = SINKS.create("html_file", {"path": str(tmp_path / "r.html")}).render(run)
    assert "<html" in text.lower()
    assert "</body></html>" in text


def test_html_escaping_of_output(tmp_path: Path):
    items = [
        ItemResult(
            item=EvalItem(id="i<1>", inputs={}, expected=None),
            output=TargetOutput(output="<script>alert('x')&"),
            scores=[ScoreResult("s", value=0.0)],
        )
    ]
    run = _run(items=items, aggregate={"s": ScoreAggregate(count=1, mean=0.0, pass_rate=0.0)})
    text = SINKS.create("html_file", {"path": str(tmp_path / "r.html")}).render(run)
    assert "<script>alert" not in text
    assert "&lt;script&gt;" in text
    assert "i&lt;1&gt;" in text


def test_non_string_output_serialized(tmp_path: Path):
    items = [
        ItemResult(
            item=EvalItem(id="i1", inputs={}, expected=None),
            output=TargetOutput(output={"b": 2, "a": 1}),
            scores=[],
        )
    ]
    run = _run(items=items, aggregate={})
    text = SINKS.create("html_file", {"path": str(tmp_path / "r.html")}).render(run)
    # dict rendered as JSON with sorted keys for stability; quotes HTML-escaped
    assert "&quot;a&quot;: 1" in text
    assert text.index("&quot;a&quot;") < text.index("&quot;b&quot;")


def test_custom_title_and_bar_clamp(tmp_path: Path):
    run = _run(aggregate={"over": ScoreAggregate(count=1, mean=1.5, pass_rate=1.0)})
    text = SINKS.create("html_file", {"path": str(tmp_path / "r.html"), "title": "Custom"}).render(run)
    assert "<title>Custom</title>" in text
    # mean 1.5 clamps to full bar width (280), not 420
    assert 'width="280.00"' in text
