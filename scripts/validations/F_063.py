#!/usr/bin/env python3
"""Validation script for F-063 - M8 execution evidence: network-judge DI seams.

Completes ``openspec/changes/prove-m8-execution`` task 5. The execution ledger
itself (``tests/_m8_probe.py``, the ``matrix_offline`` egress guard,
``pipeline_vacuous``) landed earlier on the same change; this feature closes the
two cells that ledger could not reach.

Checks:
    1.  Seam exists and defaults off: ``OpenAIJudge.__init__`` and
        ``AnthropicJudge.__init__`` both accept ``client`` defaulting to
        ``None``, matching ``ModelTarget``'s already-shipped seam. An absent
        injection is indistinguishable from the pre-seam behaviour.
    2.  An injected client bypasses SDK construction entirely: with the SDK
        module removed from ``sys.modules``, constructing either judge with a
        client leaves it unimported. Checking only that ``judge.client`` is the
        sentinel would pass even if the constructor built a real client and
        discarded it -- which is the network egress the seam exists to prevent.
    3.  Zero socket connects at construction, asserted at ``socket.connect``
        rather than inferred.
    4.  The seam is load-bearing, not decorative: the M8 ``openai_judge``
        pipeline asserts the judge's *parsed verdict*, so the cell can only pass
        if the injected client was actually called and its streamed JSON parsed.
    5.  A pipeline declaring a component it never invokes is refused by
        ``pipeline_vacuous`` -- the regression test for the vacuous
        ``echo_exact_match`` cell that motivated the whole change.

Exit codes:
    0 - all checks passed
    1 - one or more checks failed
"""

from __future__ import annotations

import inspect
import logging
import os
import socket
import sys
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from _common import check as _check
from _common import configure_logging, report

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))
sys.path.insert(0, PROJECT_ROOT)


def _check_seam_declared(errors: list[str]) -> None:
    from eval_harness.judges import AnthropicJudge, OpenAIJudge
    from eval_harness.targets.model import ModelTarget

    for cls in (OpenAIJudge, AnthropicJudge):
        params = inspect.signature(cls.__init__).parameters
        _check(
            "client" in params and params["client"].default is None,
            f"{cls.__name__}.__init__ accepts client=None (absent injection is unchanged behaviour)",
            errors,
        )

    _check(
        inspect.signature(ModelTarget.__init__).parameters["client"].default is None,
        "the seam mirrors ModelTarget's already-shipped client= parameter",
        errors,
    )


def _check_injection_bypasses_sdk(errors: list[str]) -> None:
    from eval_harness.judges import AnthropicJudge, OpenAIJudge

    for cls, module, kwargs in (
        (OpenAIJudge, "openai", {"model": "m"}),
        (AnthropicJudge, "anthropic", {}),
    ):
        sentinel = object()
        saved = sys.modules.pop(module, None)
        try:
            judge = cls(client=sentinel, **kwargs)
            bypassed = judge.client is sentinel and module not in sys.modules
        finally:
            if saved is not None:
                sys.modules[module] = saved
        _check(
            bypassed,
            f"{cls.__name__} with an injected client never imports {module}",
            errors,
        )


def _check_no_egress_at_construction(errors: list[str]) -> None:
    from eval_harness.judges import AnthropicJudge, OpenAIJudge

    with mock.patch.object(socket.socket, "connect", side_effect=AssertionError("egress")) as connect:
        OpenAIJudge(model="m", client=object())
        AnthropicJudge(client=object())
    _check(
        connect.call_count == 0,
        "constructing either judge with an injected client performs zero socket connects",
        errors,
    )


def _check_seam_is_load_bearing(errors: list[str]) -> None:
    """The M8 cell must assert the parsed verdict, not merely that a run completed."""
    from tests.test_matrix_eval_tools import _OFFLINE_OPENAI_SCORE, PIPELINES

    pipeline = PIPELINES.get("openai_judge")
    _check(pipeline is not None, "an M8 pipeline exercises the openai judge", errors)
    if pipeline is None:
        return

    injected = pipeline["judge"]["params"].get("client")
    _check(injected is not None, "the openai M8 pipeline injects an offline client", errors)
    _check(
        0.0 < _OFFLINE_OPENAI_SCORE < 1.0,
        "the offline client returns a distinctive score, so the cell cannot pass on a default",
        errors,
    )


def _check_vacuous_cell_is_refused(errors: list[str]) -> None:
    """A pipeline naming a component it never invokes must not be credited."""
    from tests import _matrix_coverage as mc

    declared = {
        "schema_version": "1.0",
        "run": {"name": "vacuity-probe", "seed": 1},
        "dataset": {"type": "inline", "params": {"items": [{"id": "v1", "inputs": {"q": "x"}, "expected": "x"}]}},
        "target": {"type": "echo", "params": {"output_key": "q"}},
        "scorers": [{"type": "exact_match", "params": {"name": "acc"}}],
        # Declared and never invoked: no scorer here reads a judge verdict.
        "judge": {"type": "mock"},
        "sinks": [{"type": "console"}],
    }
    executed = {"vac": {"dataset": {"inline"}, "target": {"echo"}, "scorer": {"exact_match"}, "sink": {"console"}}}
    vacuous = mc.pipeline_vacuous({"vac": declared}, executed)

    _check(
        vacuous.get("vac", {}).get("judge") == {"mock"},
        "a declared-but-uninvoked judge is reported as vacuous, not credited",
        errors,
    )


def main() -> int:
    configure_logging()
    errors: list[str] = []
    _check_seam_declared(errors)
    _check_injection_bypasses_sdk(errors)
    _check_no_egress_at_construction(errors)
    _check_seam_is_load_bearing(errors)
    _check_vacuous_cell_is_refused(errors)
    return report(logger, "F-063", errors)


if __name__ == "__main__":
    sys.exit(main())
