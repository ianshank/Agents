#!/usr/bin/env python3
"""Validation script for F-021 - HTML dashboard export sink.

Checks:
    1. ``HtmlFileSink`` is registered as ``"html_file"`` with alias ``"html"``.
    2. ``emit`` writes a single self-contained HTML file (no external resources).
    3. The report contains the run_id and each aggregate score name.
    4. Rendering the same ``RunResult`` twice is byte-identical (determinism).
    5. Existing sinks (console, json_file, langfuse) are still registered.

Exit codes:
    0 - all checks passed
    1 - one or more checks failed
"""

from __future__ import annotations

import logging
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from _common import check as _check
from _common import configure_logging, report

logger = logging.getLogger(__name__)

# Markers for *external* resource references - the SVG xmlns namespace URI
# (http://www.w3.org/2000/svg) is NOT an external fetch, so it is excluded.
_EXTERNAL_RESOURCE = re.compile(r"""(<script[^>]*\ssrc=|<link[^>]*\shref=|@import|url\(\s*['"]?https?:)""", re.I)


def _sample_run():
    from eval_harness.core.types import (
        EvalItem,
        ItemResult,
        RunResult,
        ScoreAggregate,
        ScoreResult,
        TargetOutput,
    )

    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    item = ItemResult(
        item=EvalItem(id="i1", inputs={"q": "<b>hi</b>"}, expected="x"),
        output=TargetOutput(output="<b>hi</b>"),
        scores=[ScoreResult("accuracy", value=1.0, passed=True)],
    )
    return RunResult(
        run_id="run-021",
        config_name="demo",
        items=[item],
        aggregate={"accuracy": ScoreAggregate(count=1, mean=1.0, pass_rate=1.0)},
        started_at=ts,
        finished_at=ts,
    )


def main() -> int:
    configure_logging()
    errors: list[str] = []

    try:
        from eval_harness.plugins import SINKS, bootstrap

        bootstrap()
    except Exception as exc:  # pragma: no cover - import guard
        logger.error("Cannot bootstrap plugins: %s", exc)
        return 1

    # 1. registration + alias
    _check("html_file" in SINKS, "HtmlFileSink registered as 'html_file'", errors)
    _check("html" in SINKS, "HtmlFileSink alias 'html' registered", errors)
    _check(SINKS.resolve("html") == "html_file", "alias 'html' resolves to 'html_file'", errors)

    # 2-4. emit, self-contained, determinism
    try:
        run = _sample_run()
        from eval_harness.sinks import HtmlFileSink

        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "nested" / "report.html"
            sink = SINKS.create("html_file", {"path": str(out)})
            # SINKS.create returns the ResultSink protocol; narrow to HtmlFileSink
            # (runtime-checked) so the concrete .render() call below type-checks.
            assert isinstance(sink, HtmlFileSink)
            sink.emit(run)
            _check(out.exists(), "emit wrote the HTML file (nested dir created)", errors)
            text = out.read_text(encoding="utf-8")
            _check("<html" in text.lower(), "output is an HTML document", errors)
            _check("run-021" in text, "report contains the run_id", errors)
            _check("accuracy" in text, "report contains the aggregate score name", errors)
            _check(
                _EXTERNAL_RESOURCE.search(text) is None,
                "report is self-contained (no external script/link/@import/url(http))",
                errors,
            )
            _check("<b>hi</b>" not in text, "user output is HTML-escaped", errors)

            # determinism: re-render the same RunResult
            second = sink.render(run)
            _check(second == text, "same RunResult renders byte-identically", errors)
    except Exception as exc:
        errors.append(f"HtmlFileSink emit/render failed: {exc}")
        logger.error("HtmlFileSink emit/render failed: %s", exc)

    # 5. existing sinks intact
    for name in ("console", "json_file", "langfuse"):
        _check(name in SINKS, f"existing sink '{name}' still registered", errors)

    return report(logger, "F-021", errors)


if __name__ == "__main__":
    sys.exit(main())
