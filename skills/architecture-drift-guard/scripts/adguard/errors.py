"""Exception hierarchy for the architecture-drift-guard library.

A single base (:class:`AdGuardError`) lets callers catch every domain error in
one place; the leaf types keep failure modes greppable and let the thin runners
map each cause to a distinct exit message without string-matching.
"""

from __future__ import annotations


class AdGuardError(Exception):
    """Base class for all architecture-drift-guard errors."""


class ManifestError(AdGuardError):
    """The manifest is missing, malformed, or fails validation/migration."""


class ExtractionError(AdGuardError):
    """The import graph could not be extracted (e.g. a root is not importable)."""


class DriftError(AdGuardError):
    """Architecture drift was detected (undocumented component edges)."""
