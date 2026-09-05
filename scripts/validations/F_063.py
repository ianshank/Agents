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
    4.  The seam is load-bearing, not decorative -- established by *running*
        every seam judge's M8 pipeline here, offline, twice against two
        different injected verdicts, and requiring the aggregate to track
        whichever verdict was injected. A judge that ignored its client and
        answered a constant matches at most one of the two.
    5.  A pipeline declaring a component it never invokes is refused by
        ``pipeline_vacuous`` -- the regression test for the vacuous
        ``echo_exact_match`` cell that motivated the whole change.

Exit codes:
    0 - all checks passed
    1 - one or more checks failed
"""

from __future__ import annotations

import copy
import inspect
import logging
import os
import socket
import sys
from collections.abc import Callable
from typing import Any
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

#: Registered judges this feature ships a ``client=`` seam for. A *checked* declaration
#: in the ADR 0032 rule-2 sense, not a free-standing list: :func:`_seam_judges` derives
#: the same set from the live registry and check 1 fails if the two disagree. Discovery
#: alone would pass vacuously the moment a seam were deleted; a hand-written list alone
#: would silently miss a third network judge added later. Cross-checked, either fails.
_DECLARED_SEAM_JUDGES = ("anthropic", "openai")

#: Verdicts check 4 injects. Distinct from each other and from every plausible default
#: (0.0, 0.5, 1.0), because the check runs each cell once per verdict and requires the
#: aggregate to follow: a judge that ignored its client and answered a constant can
#: match at most one of the two, whatever constant it picked.
_PROBE_VERDICTS = (0.23, 0.71)


def _seam_judges() -> dict[str, type]:
    """Registered judges whose ``__init__`` accepts ``client`` defaulting to ``None``.

    Read off the live registry rather than named here, so a third network judge that
    grows the seam is held to check 4's contract without editing this validator.
    """
    from eval_harness.plugins import JUDGES, bootstrap

    bootstrap()
    found: dict[str, type] = {}
    for name in JUDGES.names():
        cls = JUDGES.get(name)
        param = inspect.signature(cls.__init__).parameters.get("client")
        if param is not None and param.default is None:
            found[name] = cls
    return found


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

    discovered = sorted(_seam_judges())
    _check(
        discovered == sorted(_DECLARED_SEAM_JUDGES),
        f"registry discovery finds exactly the declared seam judges {sorted(_DECLARED_SEAM_JUDGES)}, "
        f"not {discovered} -- check 4 runs one M8 cell per discovered judge, so a judge that grew "
        "a seam without a cell, and a declaration that outlived its seam, both fail here",
        errors,
    )

    _check(
        inspect.signature(ModelTarget.__init__).parameters["client"].default is None,
        "the seam mirrors ModelTarget's already-shipped client= parameter",
        errors,
    )


def _check_injection_bypasses_sdk(errors: list[str]) -> None:
    from eval_harness.judges import AnthropicJudge, OpenAIJudge

    # Unrolled rather than looped over (class, kwargs) pairs: the two constructors
    # take different required arguments, and a loop erases that into **kwargs that
    # mypy cannot check against either signature.
    def _bypasses(module: str, build: Callable[[object], Any]) -> bool:
        sentinel = object()
        saved = sys.modules.pop(module, None)
        try:
            return build(sentinel).client is sentinel and module not in sys.modules
        finally:
            if saved is not None:
                sys.modules[module] = saved

    _check(
        _bypasses("openai", lambda c: OpenAIJudge(model="m", client=c)),
        "OpenAIJudge with an injected client never imports openai",
        errors,
    )
    _check(
        _bypasses("anthropic", lambda c: AnthropicJudge(client=c)),
        "AnthropicJudge with an injected client never imports anthropic",
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


def _seam_cells() -> dict[str, dict[str, Any]]:
    """M8 pipelines that inject a ``client`` into their judge, found by shape.

    Matched on the injection rather than on a pipeline name, so the two cells are
    discovered the same way a third would be.
    """
    from tests.test_matrix_eval_tools import PIPELINES

    return {
        name: cfg
        for name, cfg in PIPELINES.items()
        if isinstance(cfg.get("judge"), dict) and "client" in cfg["judge"].get("params", {})
    }


def _run_seam_cell(pipeline: dict[str, Any], client: Any) -> tuple[Any, Any, int]:
    """Run one M8 judge pipeline end to end against *client*, offline.

    Returns ``(result, execution ledger, socket connects observed)``. Egress is
    asserted at ``socket.connect`` rather than inferred, mirroring check 3 -- the
    pytest cells get this from the ``matrix_offline`` marker, which a validator run
    outside pytest does not have.
    """
    from tests._m8_probe import probe

    from eval_harness.config import EvalConfig
    from eval_harness.engine import EvalEngine

    config_dict = copy.deepcopy(pipeline)
    # Injected AFTER the deepcopy, so the object whose `.calls` the caller reads is the
    # one the engine actually used and not a copy of it.
    config_dict["judge"]["params"]["client"] = client
    config = EvalConfig.model_validate(config_dict)

    with (
        mock.patch.object(socket.socket, "connect", side_effect=AssertionError("egress")) as connect,
        probe() as ledger,
    ):
        result = EvalEngine.from_config(config).run()
    return result, ledger, connect.call_count


def _check_cell_tracks_its_client(name: str, pipeline: dict[str, Any], errors: list[str]) -> None:
    """Run one seam cell twice, against two different verdicts, and require it to follow."""
    from tests.test_matrix_eval_tools import _SWALLOW_MARKER

    judge = pipeline["judge"]["type"]
    # A fresh instance of whatever fixture the cell ships, so the shape of the stand-in
    # (streamed chunks vs content blocks) stays the test module's business, not this one's.
    fixture = type(pipeline["judge"]["params"]["client"])

    for verdict in _PROBE_VERDICTS:
        client = fixture(verdict)
        try:
            result, ledger, connects = _run_seam_cell(pipeline, client)
        except Exception as exc:  # a cell that crashes is a failed check, not a traceback
            _check(False, f"M8 cell {name!r} runs offline against an injected client (raised {exc!r})", errors)
            return

        _check(connects == 0, f"M8 cell {name!r} opens zero sockets while the {judge!r} judge runs", errors)
        _check(ledger.invoked("judge", judge), f"M8 cell {name!r} invokes the {judge!r} judge's evaluate", errors)
        _check(bool(client.calls), f"M8 cell {name!r} calls the injected client rather than a real one", errors)
        _check(
            not any(
                (score.comment or "").startswith(_SWALLOW_MARKER) for item in result.items for score in item.scores
            ),
            f"M8 cell {name!r} records no swallowed scorer exception (the engine turns one into a silent 0.0)",
            errors,
        )
        _check(
            verdict in {agg.mean for agg in result.aggregate.values()},
            f"M8 cell {name!r} aggregates the verdict its injected client returned ({verdict}); "
            f"observed {sorted({agg.mean for agg in result.aggregate.values()})}",
            errors,
        )


def _check_seam_is_load_bearing(errors: list[str]) -> None:
    """Run each seam judge's M8 cell here, rather than asserting that one exists.

    The first cut of this function read the pipeline dict and the fixture's score
    constant off ``tests.test_matrix_eval_tools`` and concluded *from their shape* that
    the cell was falsifiable. That is the defect this whole feature exists to remove --
    crediting a declaration instead of an execution -- reintroduced one layer down,
    inside the validator that proves the feature. Found by an automated PR review.
    """
    cells = _seam_cells()
    covered = {cfg["judge"]["type"]: name for name, cfg in cells.items()}

    for judge in sorted(_seam_judges()):
        if not _check(judge in covered, f"an M8 pipeline injects a client into the {judge!r} judge", errors):
            continue
        name = covered[judge]
        _check_cell_tracks_its_client(name, cells[name], errors)


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
