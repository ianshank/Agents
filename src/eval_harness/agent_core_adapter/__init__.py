"""agent-core integration adapter for the eval-harness.

Bridges the harness's LLM-judge subsystem to agent-core's deterministic
loop control, allowing :class:`~agent_core.LoopController` to orchestrate
multi-cycle evaluations with budget enforcement and convergence detection.

Prerequisites
-------------
Install agent-core from the monorepo before importing this module::

    pip install -e "./agent-core"

All tunables live in :class:`AdapterConfig`; no literals appear in logic.

Module layout
-------------
Split by concern, following ADR-0019's ``store_sync/`` precedent:
``config.py`` (:class:`AdapterConfig`), ``bridge.py`` (the harness<->agent-core
bridge -- see its docstring for the Claim-ID mapping contract), ``budget.py``
(judge cost/rate-limiting), ``gate_authorization.py`` (judge-calibration gate
authorization), and ``calibration.py`` (panel-member agreement). Every public
name is re-exported here, so existing
``from eval_harness.agent_core_adapter import X`` call sites keep working
unchanged.
"""

from __future__ import annotations


def _is_agent_core_import_error(exc: ImportError) -> bool:
    """True iff *exc*'s failing module is ``agent_core`` (or one of its submodules).

    ``.bridge``/``.gate_authorization`` also import plain eval_harness modules (core
    interfaces/types, ``.config``) that have nothing to do with agent-core. Only an
    import failure actually rooted in ``agent_core`` should be reworded as "agent-core
    is required" below -- anything else must re-raise unchanged, so a real bug inside
    this package's own submodules surfaces as itself, not a misleading message that
    sends a reader chasing the wrong cause.
    """
    return exc.name == "agent_core" or (exc.name is not None and exc.name.startswith("agent_core."))


try:
    from .bridge import FixedCostEstimator, HarnessJudgeRunner, ItemStore
    from .gate_authorization import require_report_to_gate
except ImportError as _exc:  # pragma: no cover -- see test_is_agent_core_import_error for the branch logic
    if _is_agent_core_import_error(_exc):
        raise ImportError(
            "agent-core is required for eval_harness.agent_core_adapter. "
            "Install it from the monorepo: pip install -e './agent-core'"
        ) from _exc
    raise

from .budget import BudgetedJudge, build_budgeted_judge  # noqa: E402
from .budget import _SlidingWindowLimiter as _SlidingWindowLimiter  # noqa: E402
from .calibration import pairwise_member_kappa  # noqa: E402
from .config import AdapterConfig  # noqa: E402

__all__ = [
    "AdapterConfig",
    "BudgetedJudge",
    "FixedCostEstimator",
    "HarnessJudgeRunner",
    "ItemStore",
    "build_budgeted_judge",
    "pairwise_member_kappa",
    "require_report_to_gate",
]
