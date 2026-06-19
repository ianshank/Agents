"""architecture-drift-guard library.

Self-contained (depends only on ``grimp`` + ``pyyaml``). The public surface is
small and composable: load a manifest, extract the real import graph, fold it to
components, diff against declared edges, and render the C4 diagram. The grimp
call is isolated in :mod:`adguard.extractor` so a non-Python extractor is an
additive change.
"""

from __future__ import annotations

from .differ import DiffResult, diff_edges, format_report
from .emit import emit_dependencies_block
from .errors import AdGuardError, DriftError, ExtractionError, ManifestError
from .extractor import extract_graph
from .folding import fold_to_components, module_to_component
from .logging_util import configure_logging, debug_span, get_logger
from .manifest import Manifest, load_manifest, validate
from .mermaid import render_mermaid
from .migrations import SCHEMA_VERSION

__version__ = "1.0.0"

__all__ = [
    "SCHEMA_VERSION",
    "AdGuardError",
    "DiffResult",
    "DriftError",
    "ExtractionError",
    "Manifest",
    "ManifestError",
    "__version__",
    "configure_logging",
    "debug_span",
    "diff_edges",
    "emit_dependencies_block",
    "extract_graph",
    "fold_to_components",
    "format_report",
    "get_logger",
    "load_manifest",
    "module_to_component",
    "render_mermaid",
    "validate",
]
