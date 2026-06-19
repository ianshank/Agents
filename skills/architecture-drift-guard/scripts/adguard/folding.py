"""Fold a module-level import graph down to component-level edges.

A *component* owns one or more package prefixes (from the manifest). Each module
is mapped to the component owning its **longest** matching prefix, so nested
components resolve to the most specific owner (e.g. ``pkg.core.types`` belongs to
a ``pkg.core.types`` component, not a broader ``pkg.core`` one).

Only DIRECT, cross-component edges survive: intra-component edges and edges
touching unmapped modules are dropped (and logged at DEBUG). This module is pure
— no third-party imports — so it is trivially testable and deterministic.
"""

from __future__ import annotations

from collections.abc import Mapping

from .logging_util import debug_span, get_logger
from .manifest import Edge

logger = get_logger(__name__)


def _prefix_index(components: Mapping[str, list[str]]) -> list[tuple[str, str]]:
    """Return (prefix, component) pairs sorted by prefix length, longest first."""
    pairs: list[tuple[str, str]] = []
    for name, prefixes in components.items():
        for prefix in prefixes:
            pairs.append((prefix, name))
    # Longest prefix wins; ties broken deterministically by prefix then name.
    pairs.sort(key=lambda pc: (-len(pc[0]), pc[0], pc[1]))
    return pairs


def module_to_component(module: str, index: list[tuple[str, str]]) -> str | None:
    """Map a module to its owning component via longest-prefix match."""
    for prefix, name in index:
        if module == prefix or module.startswith(prefix + "."):
            return name
    return None


def fold_to_components(
    module_graph: Mapping[str, set[str]],
    components: Mapping[str, list[str]],
) -> set[Edge]:
    """Collapse module->module edges into the set of direct component edges."""
    index = _prefix_index(components)
    edges: set[Edge] = set()
    with debug_span(logger, "fold_to_components", modules=len(module_graph), components=len(components)):
        for module, imported in module_graph.items():
            src = module_to_component(module, index)
            if src is None:
                logger.debug("unmapped module skipped: %s", module)
                continue
            for target in imported:
                dst = module_to_component(target, index)
                if dst is None:
                    logger.debug("import to unmapped module skipped: %s -> %s", module, target)
                    continue
                if src == dst:
                    continue  # intra-component edge
                edges.add((src, dst))
    logger.debug("folded to %d component edge(s)", len(edges))
    return edges
