#!/usr/bin/env python3
"""Shared config + changed-file helpers for the ``scripts/`` tooling.

Single-sources the two idioms that ``merge_gate_context.py`` and ``agent_confidence.py``
had each spelled themselves: resolving a changed-file set from ``--files``/``--files-from``,
and strictly loading a schema-versioned YAML mapping. ``ConfigError`` is re-exported from
``check_protected_changes`` (its original home) so callers have one import site; this module
never imports anything that would form a cycle.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence

import yaml
from check_protected_changes import ConfigError

__all__ = [
    "SUPPORTED_SCHEMA_MAJOR",
    "ConfigError",
    "load_yaml_mapping",
    "read_nul_delimited",
    "require_exact_keys",
    "require_major",
    "resolve_explicit_files",
]

# Schema-version major supported by the strict YAML configs under config/ (additive minor
# bumps stay compatible; a major bump is a deliberate breaking cutover).
SUPPORTED_SCHEMA_MAJOR = "1"


def read_nul_delimited(path: str) -> list[str]:
    """Read a NUL-delimited path list (``git diff --name-only -z`` output).

    Read as bytes and decode with ``surrogateescape`` — that output is a raw byte stream and
    a path may contain non-UTF-8 bytes, which strict text mode would raise ``UnicodeDecodeError``
    on. Unreadable file -> ``ConfigError`` (so the CLI exits with its config code, never crashes).
    """
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        raise ConfigError(f"cannot read --files-from '{path}': {exc}") from exc
    text = raw.decode("utf-8", "surrogateescape")
    return [f for f in text.split("\0") if f.strip()]


def resolve_explicit_files(files: Sequence[str] | None, files_from: str | None) -> list[str] | None:
    """The shared ``--files`` / ``--files-from`` resolution.

    Returns the changed-file list when either flag is given (possibly empty after stripping),
    or ``None`` when neither is given — the signal for the caller to fall back to its own source
    (a live ``git diff`` for ``merge_gate_context``, or an empty set for ``agent_confidence``).
    """
    if files:
        return [f for f in files if f.strip()]
    if files_from:
        return read_nul_delimited(files_from)
    return None


def load_yaml_mapping(path: str) -> dict:
    """Load a YAML file that must be a mapping; any I/O or parse error -> ``ConfigError``."""
    try:
        with open(path, encoding="utf-8") as fh:
            doc = yaml.safe_load(fh)
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"cannot read config '{path}': {exc}") from exc
    if not isinstance(doc, dict):
        raise ConfigError(f"config '{path}' must be a mapping")
    return doc


def require_major(version: str, path: str, supported: str = SUPPORTED_SCHEMA_MAJOR) -> None:
    """Reject a schema_version whose major differs from ``supported``."""
    if version.split(".", 1)[0] != supported:
        raise ConfigError(f"unsupported schema_version {version!r} in '{path}' (supported major: {supported}.x)")


def require_exact_keys(doc: Collection[str], expected: Collection[str], label: str) -> None:
    """Reject a mapping whose top-level keys are not exactly ``expected``."""
    if set(doc) != set(expected):
        raise ConfigError(f"{label} keys must be exactly {sorted(set(expected))}; got {sorted(set(doc))}")
