"""Version metadata for langfuse-eval-harness."""

from __future__ import annotations

import importlib.metadata

# Distribution name as registered in pyproject.toml — NOT __name__
_DIST_NAME = "langfuse-eval-harness"

try:
    __version__: str = importlib.metadata.version(_DIST_NAME)
except importlib.metadata.PackageNotFoundError:
    # Editable install or running from source without pip install
    __version__ = "0.0.0-dev"

# Config schema version — decoupled from package version.
# Bumped only when the YAML config format changes.
SCHEMA_VERSION = "1.0"
