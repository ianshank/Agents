"""Built-in target runners (the system-under-test adapters)."""
from __future__ import annotations

import importlib
import time
from collections.abc import Callable
from typing import Any

from ..core.interfaces import TargetRunner
from ..core.types import EvalItem, TargetOutput
from ..plugins import TARGETS


@TARGETS.register("echo")
class EchoTarget(TargetRunner):
    """Returns the input (optionally a single field). Handy for wiring tests."""

    def __init__(self, output_key: str | None = None):
        self.output_key = output_key

    def run(self, item: EvalItem) -> TargetOutput:
        if self.output_key is not None:
            return TargetOutput(output=item.inputs.get(self.output_key))
        return TargetOutput(output=item.inputs)


@TARGETS.register("callable", aliases=("python",))
class CallableTarget(TargetRunner):
    """Dynamically imports ``module:function`` and calls it with item inputs.

    This is the extensibility seam for real systems-under-test: point it at any
    callable that accepts the inputs dict and returns the output.
    """

    def __init__(self, path: str, pass_item: bool = False):
        self.path = path
        self.pass_item = pass_item
        self._fn: Callable[..., Any] | None = None

    def _resolve(self) -> Callable[..., Any]:
        if self._fn is None:
            module_name, _, attr = self.path.partition(":")
            if not attr:
                raise ValueError(f"target path {self.path!r} must be 'module:function'")
            module = importlib.import_module(module_name)
            self._fn = getattr(module, attr)
        return self._fn

    def run(self, item: EvalItem) -> TargetOutput:
        fn = self._resolve()
        start = time.perf_counter()
        try:
            result = fn(item) if self.pass_item else fn(item.inputs)
            latency = (time.perf_counter() - start) * 1000
            return TargetOutput(output=result, latency_ms=latency)
        except Exception as exc:  # surface target failures as scored errors
            latency = (time.perf_counter() - start) * 1000
            return TargetOutput(output=None, error=str(exc), latency_ms=latency)
