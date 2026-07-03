"""Load, migrate, interpolate and validate the architecture manifest.

Pipeline (mirrors ``eval_harness.config``): read YAML -> migrate to current
schema -> interpolate ``${ENV_VARS}`` -> apply CLI overrides -> validate into a
:class:`Manifest`. Env interpolation keeps environment-specific values (repo
roots, source paths, output locations) out of the committed manifest, satisfying
the no-hardcoded-values requirement end to end.

The manifest is the single source of truth: root packages to analyse, the
component map (name -> package prefixes), the declared component dependency
edges, optional ``sys_path`` entries to make the roots importable, and an
optional ``output`` block (e.g. where the generated Mermaid lives).

Validation is hand-written (no pydantic): the skill's runtime dependency surface
is intentionally limited to ``grimp`` + ``pyyaml``.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .errors import ManifestError
from .migrations import SCHEMA_VERSION, migrate_to_current

# ${VAR} or ${VAR:-default}
_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")

# Default location for the generated Mermaid diagram if the manifest's ``output``
# block does not specify one. Resolved here (not inline in the runner) so callers
# never embed the literal.
DEFAULT_MERMAID_PATH = "architecture.mmd"

# Component edges are DIRECT, not transitive. An edge ``(a, b)`` means component
# ``a`` directly imports something in component ``b``.
Edge = tuple[str, str]


def _interpolate_str(value: str, env: Mapping[str, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        var, default = match.group(1), match.group(2)
        if var in env:
            return env[var]
        if default is not None:
            return default
        raise ManifestError(f"environment variable {var!r} is not set and has no default")

    return _ENV_PATTERN.sub(repl, value)


def _coerce_scalar(text: str) -> Any:
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError:
        return text


def interpolate(obj: Any, env: Mapping[str, str]) -> Any:
    """Recursively expand ``${VAR}`` / ``${VAR:-default}`` tokens.

    A value that is *exactly* one token is coerced back to its native YAML scalar
    (so ``"true"`` -> ``True``); tokens embedded in a larger string (e.g. a path)
    stay strings.
    """
    if isinstance(obj, str):
        if _ENV_PATTERN.fullmatch(obj):
            return _coerce_scalar(_interpolate_str(obj, env))
        return _interpolate_str(obj, env)
    if isinstance(obj, list):
        return [interpolate(v, env) for v in obj]
    if isinstance(obj, dict):
        return {k: interpolate(v, env) for k, v in obj.items()}
    return obj


def apply_overrides(raw: dict, overrides: Iterable[str]) -> dict:
    """Apply dotted-path overrides like ``output.mermaid_path=docs/arch.mmd``."""
    for override in overrides:
        if "=" not in override:
            raise ManifestError(f"override {override!r} must be of form key.path=value")
        path, _, value = override.partition("=")
        keys = path.split(".")
        node = raw
        for key in keys[:-1]:
            node = node.setdefault(key, {})
            if not isinstance(node, dict):
                raise ManifestError(f"cannot set {path!r}: {key!r} is not a mapping")
        node[keys[-1]] = _coerce_scalar(value)
    return raw


@dataclass
class Manifest:
    """The validated architecture manifest."""

    schema_version: str
    root_packages: list[str]
    components: dict[str, list[str]]  # component name -> package prefixes
    dependencies: set[Edge]  # declared DIRECT component edges (from, to)
    sys_path: list[str] = field(default_factory=list)
    output: dict[str, Any] = field(default_factory=dict)

    def mermaid_path(self) -> str:
        """Where the generated Mermaid diagram should live (manifest-driven)."""
        return str(self.output.get("mermaid_path", DEFAULT_MERMAID_PATH))

    def component_names(self) -> set[str]:
        return set(self.components)


def _parse_dependencies(raw_deps: Any) -> set[Edge]:
    """Normalise the ``dependencies`` block into a set of (from, to) edges.

    Accepts a mapping ``{from: [to, ...]}`` (the form emitted by ``--emit-actual``).
    A component with no outgoing edges may map to ``null`` or ``[]``.
    """
    if raw_deps is None:
        return set()
    if not isinstance(raw_deps, dict):
        raise ManifestError("'dependencies' must be a mapping of component -> [components]")
    edges: set[Edge] = set()
    for src, targets in raw_deps.items():
        if targets is None:
            continue
        if not isinstance(targets, list):
            raise ManifestError(f"dependencies[{src!r}] must be a list of component names")
        for dst in targets:
            edges.add((str(src), str(dst)))
    return edges


def _build_manifest(raw: dict[str, Any]) -> Manifest:
    components_raw = raw.get("components", {})
    if not isinstance(components_raw, dict):
        raise ManifestError("'components' must be a mapping of name -> [package prefixes]")
    components: dict[str, list[str]] = {}
    for name, prefixes in components_raw.items():
        if not isinstance(prefixes, list):
            raise ManifestError(f"components[{name!r}] must be a list of package prefixes")
        components[str(name)] = [str(p) for p in prefixes]

    root_packages = raw.get("root_packages", [])
    if not isinstance(root_packages, list):
        raise ManifestError("'root_packages' must be a list")

    sys_path = raw.get("sys_path", [])
    if not isinstance(sys_path, list):
        raise ManifestError("'sys_path' must be a list of directories")

    output = raw.get("output", {})
    if not isinstance(output, dict):
        raise ManifestError("'output' must be a mapping")

    return Manifest(
        schema_version=str(raw.get("schema_version", "")),
        root_packages=[str(p) for p in root_packages],
        components=components,
        dependencies=_parse_dependencies(raw.get("dependencies")),
        sys_path=[str(p) for p in sys_path],
        output=output,
    )


def validate(manifest: Manifest) -> None:
    """Raise :class:`ManifestError` if the manifest is internally inconsistent."""
    if manifest.schema_version != SCHEMA_VERSION:
        raise ManifestError(f"schema_version {manifest.schema_version!r} != current {SCHEMA_VERSION!r}")
    if not manifest.root_packages:
        raise ManifestError("'root_packages' must list at least one importable package")
    if any(not p for p in manifest.root_packages):
        raise ManifestError("'root_packages' contains an empty entry")
    if not manifest.components:
        raise ManifestError("'components' must define at least one component")

    known = manifest.component_names()
    for name, prefixes in manifest.components.items():
        if not name:
            raise ManifestError("component name must be non-empty")
        if not prefixes:
            raise ManifestError(f"component {name!r} has no package prefixes")
        if any(not p for p in prefixes):
            raise ManifestError(f"component {name!r} has an empty package prefix")

    for src, dst in manifest.dependencies:
        if src not in known:
            raise ManifestError(f"declared edge from unknown component {src!r}")
        if dst not in known:
            raise ManifestError(f"declared edge to unknown component {dst!r}")
        if src == dst:
            raise ManifestError(f"self-edge {src!r} -> {dst!r} is not allowed")


def load_manifest(
    path: str | Path,
    *,
    overrides: Iterable[str] | None = None,
    env: Mapping[str, str] | None = None,
) -> Manifest:
    """Load, migrate, interpolate, override, and validate a manifest file."""
    env = os.environ if env is None else env
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ManifestError(f"cannot read manifest {str(path)!r}: {exc}") from exc
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ManifestError(f"manifest {str(path)!r} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ManifestError(f"manifest at {path} did not parse to a mapping")
    raw = migrate_to_current(raw)
    raw = interpolate(raw, env)
    if overrides:
        raw = apply_overrides(raw, list(overrides))
    manifest = _build_manifest(raw)
    validate(manifest)
    return manifest
