"""Central registries plus dynamic plugin discovery.

Built-in components register themselves on import. Third-party packages can add
components at runtime via the ``eval_harness.plugins`` entry-point group, so the
harness is extensible without editing this package.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from importlib import import_module
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
    for module_name in ("datasets", "judges", "scorers", "sinks", "targets"):
        import_module(f"{__package__}.{module_name}")


def load_entry_point_plugins() -> None:
    """Discover third-party plugins registered via package entry points."""
    try:
        from importlib.metadata import entry_points

        eps = entry_points()
        selected: Iterable[Any]
        if hasattr(eps, "select"):
            selected = eps.select(group=ENTRY_POINT_GROUP)
        else:  # pragma: no cover - py<3.10 shim
            selected = cast("dict[str, list[Any]]", eps).get(ENTRY_POINT_GROUP, [])
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
