"""Single source of truth for package and config-schema versions."""
from __future__ import annotations

__version__ = "1.0.0"

# Current configuration schema version. Older configs are migrated up to this
# value at load time (see eval_harness.config.migrations), which is what makes
# the harness backwards compatible with previously authored config files.
SCHEMA_VERSION = "1.0"
