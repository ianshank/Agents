"""Extract the actual import graph with grimp — the ONE grimp-bound module.

Isolating grimp here means a future extractor for another language (e.g. SCIP
for TypeScript) is an additive sibling implementing the same
``extract_graph`` contract, not a rewrite. Everything downstream (folding,
diffing, rendering) consumes the plain ``dict[module] -> set[imported modules]``
this returns and never imports grimp.

Edges are DIRECT, not transitive: at the component level, transitive folding
makes nearly everything depend on everything and the signal dies. We therefore
use grimp's direct-import query exclusively.
"""

from __future__ import annotations

from collections.abc import Sequence

from .errors import ExtractionError
from .logging_util import debug_span, get_logger

logger = get_logger(__name__)


def extract_graph(root_packages: Sequence[str]) -> dict[str, set[str]]:
    """Build the direct import graph for ``root_packages``.

    Returns a mapping ``module -> set(directly imported internal modules)``. Each
    root package must be importable (on ``sys.path``); the runner is responsible
    for prepending the manifest's ``sys_path`` entries before calling this.

    Raises :class:`ExtractionError` if grimp is missing or a package cannot be
    analysed.
    """
    try:
        import grimp
    except ImportError as exc:  # pragma: no cover - exercised via integration, not unit
        raise ExtractionError("grimp is required for import extraction; install it (pip install grimp)") from exc

    roots = list(root_packages)
    with debug_span(logger, "grimp.build_graph", roots=",".join(roots)):
        try:
            graph = grimp.build_graph(*roots)
        except Exception as exc:
            raise ExtractionError(f"could not build import graph for {roots!r}: {exc}") from exc

    result: dict[str, set[str]] = {}
    for module in graph.modules:
        result[module] = set(graph.find_modules_directly_imported_by(module))
    logger.debug("extracted %d module(s) from roots %s", len(result), roots)
    return result
