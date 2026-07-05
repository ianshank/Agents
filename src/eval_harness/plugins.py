"""Central registries plus dynamic plugin discovery.

Built-in components register themselves on import. Third-party packages can add
components at runtime via the ``eval_harness.plugins`` entry-point group, so the
harness is extensible without editing this package.
"""

from __future__ import annotations

import logging
from typing import Any, cast

from .core.interfaces import DatasetSource, Judge, ResultSink, Scorer, TargetRunner
from .core.registry import Registry

log = logging.getLogger(__name__)

SCORERS: Registry[Scorer] = Registry("scorer")
DATASETS: Registry[DatasetSource] = Registry("dataset")
TARGETS: Registry[TargetRunner] = Registry("target")
SINKS: Registry[ResultSink] = Registry("sink")
JUDGES: Registry[Judge] = Registry("judge")

ENTRY_POINT_GROUP = "eval_harness.plugins"

_bootstrapped = False


def load_builtin_plugins() -> None:
    """Import built-in component modules so their decorators run."""
    from . import datasets as _datasets  # noqa: F401
    from . import judges as _judges  # noqa: F401
    from . import scorers as _scorers  # noqa: F401
    from . import sinks as _sinks  # noqa: F401
    from . import targets as _targets  # noqa: F401


def load_entry_point_plugins() -> None:
    """Discover third-party plugins registered via package entry points."""
    try:
        from importlib.metadata import entry_points

        eps = entry_points()
        selected = (
            eps.select(group=ENTRY_POINT_GROUP)
            if hasattr(eps, "select")
            else cast(Any, eps).get(ENTRY_POINT_GROUP, [])  # pragma: no cover - py<3.10 shim
        )
        for ep in selected:
            try:
                ep.load()
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("Failed to load plugin %s: %s", ep.name, exc)
    except Exception as exc:  # pragma: no cover - defensive
        log.debug("Entry-point discovery skipped: %s", exc)


def bootstrap(force: bool = False) -> None:
    global _bootstrapped
    if _bootstrapped and not force:
        return
    load_builtin_plugins()
    load_entry_point_plugins()
    _bootstrapped = True
