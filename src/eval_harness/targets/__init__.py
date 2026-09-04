"""Built-in target runners (the system-under-test adapters)."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from ..core._imports import import_allowed_module
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
        """Resolve ``path`` to a callable, refusing modules the operator has not
        allowed.

        ``import_allowed_module`` replaces a bare ``importlib.import_module``:
        this method turns a configuration string into executed code, so the
        module has to clear ``EVAL_HARNESS_CALLABLE_TARGET_ALLOWLIST`` *before*
        it is imported. Deliberately still lazy -- resolving in ``__init__``
        would move the failure to registry construction and change when an
        unresolvable path is reported.
        """
        if self._fn is None:
            module_name, _, attr = self.path.partition(":")
            if not attr:
                raise ValueError(f"target path {self.path!r} must be 'module:function'")
            module = import_allowed_module(module_name)
            self._fn = getattr(module, attr)
        return self._fn

    def run(self, item: EvalItem) -> TargetOutput:
        fn = self._resolve()
        start = time.perf_counter()
        try:
            result = fn(item) if self.pass_item else fn(item.inputs)
            latency = (time.perf_counter() - start) * 1000
            if isinstance(result, TargetOutput):
                # A callable that builds its own TargetOutput passes straight through, so
                # a tool-using agent can attach an AgentTrajectory (F-051) without needing
                # a bespoke TargetRunner class. Latency is filled in only when the callable
                # did not measure it itself. Callables returning a plain value are
                # unaffected — this branch simply never fires for them.
                if result.latency_ms is None:
                    result.latency_ms = latency
                return result
            return TargetOutput(output=result, latency_ms=latency)
        except Exception as exc:  # surface target failures as scored errors
            latency = (time.perf_counter() - start) * 1000
            return TargetOutput(output=None, error=str(exc), latency_ms=latency)


# Importing the module runs the ``@TARGETS.register("model")`` decorator. Kept at
# the bottom so the simple targets above register first; the E402/F401 suppressions
# below exist because this is an intentional register-on-import side effect, not unused.
from . import model  # noqa: E402, F401
