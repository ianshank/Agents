"""Shared serialization helpers for displaying arbitrary values as stable text.

Lives in ``core`` (which depends on nothing) so any component can reuse it
without creating an import cycle. Both the scorers and the sinks render output
values for display; this is the single source of that convention.
"""

from __future__ import annotations

import json
from typing import Any


def as_text(value: Any) -> str:
    """Render any value as stable text: strings pass through; everything else is
    serialized to JSON with sorted keys (so dict ordering is deterministic) and a
    ``str`` fallback for non-JSON-native types.
    """
    return value if isinstance(value, str) else json.dumps(value, sort_keys=True, default=str)
