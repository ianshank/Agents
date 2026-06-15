"""Built-in result sinks."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from ..core.interfaces import ResultSink
from ..core.types import RunResult
from ..langfuse_client import LangfuseClient
from ..plugins import SINKS


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
                self.lines.append(f"  - {ir.item.id}: {[ (s.name, round(s.value,3)) for s in ir.scores ]}")
        print("\n".join(self.lines))


@SINKS.register("json_file", aliases=("json",))
class JsonFileSink(ResultSink):
    def __init__(self, path: str, indent: int = 2):
        self.path = Path(path)
        self.indent = indent

    def emit(self, run: RunResult) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(run.to_dict(), indent=self.indent, default=str))


@SINKS.register("langfuse")
class LangfuseSink(ResultSink):
    """Writes per-item scores back to Langfuse. Client injected by the engine."""

    def __init__(self, min_value_to_log: Optional[float] = None):
        self.min_value_to_log = min_value_to_log
        self._client: Optional[LangfuseClient] = None

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
