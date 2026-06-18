"""Load, migrate, interpolate and validate evaluation configs.

Pipeline: read YAML -> migrate to current schema -> interpolate ${ENV_VARS}
-> apply CLI overrides -> validate into EvalConfig.

Env interpolation keeps secrets and environment-specific values (regions, model
ids, paths, endpoints) out of the committed config, satisfying the
no-hard-coded-values requirement end to end.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import yaml

from .migrations import ConfigError, migrate_to_current
from .models import EvalConfig

# ${VAR} or ${VAR:-default}
_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _interpolate_str(value: str, env: Mapping[str, str]) -> str:
    def repl(match: re.Match) -> str:
        var, default = match.group(1), match.group(2)
        if var in env:
            return env[var]
        if default is not None:
            return default  # type: ignore[no-any-return]
        raise ConfigError(f"environment variable {var!r} is not set and has no default")

    return _ENV_PATTERN.sub(repl, value)


def interpolate(obj: Any, env: Mapping[str, str]) -> Any:
    if isinstance(obj, str):
        # A value that is *exactly* one ${..} token is coerced back to its
        # native YAML scalar (so "0.6" -> 0.6, "true" -> True). Tokens embedded
        # in a larger string (e.g. a path) stay strings.
        if _ENV_PATTERN.fullmatch(obj):
            return _coerce_scalar(_interpolate_str(obj, env))
        return _interpolate_str(obj, env)
    if isinstance(obj, list):
        return [interpolate(v, env) for v in obj]
    if isinstance(obj, dict):
        return {k: interpolate(v, env) for k, v in obj.items()}
    return obj


def _coerce_scalar(text: str) -> Any:
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError:
        return text


def apply_overrides(raw: dict, overrides: Iterable[str]) -> dict:
    """Apply dotted-path overrides like ``run.sample_rate=0.1``."""
    for override in overrides:
        if "=" not in override:
            raise ConfigError(f"override {override!r} must be of form key.path=value")
        path, _, value = override.partition("=")
        keys = path.split(".")
        node = raw
        for key in keys[:-1]:
            node = node.setdefault(key, {})
            if not isinstance(node, dict):
                raise ConfigError(f"cannot set {path!r}: {key!r} is not a mapping")
        node[keys[-1]] = _coerce_scalar(value)
    return raw


def load_config_dict(
    raw: dict,
    *,
    overrides: Iterable[str] | None = None,
    env: Mapping[str, str] | None = None,
) -> EvalConfig:
    env = os.environ if env is None else env
    raw = migrate_to_current(raw)
    raw = interpolate(raw, env)
    if overrides:
        raw = apply_overrides(raw, overrides)
    return EvalConfig.model_validate(raw)


def load_config(
    path: str | Path,
    *,
    overrides: Iterable[str] | None = None,
    env: Mapping[str, str] | None = None,
) -> EvalConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError(f"config at {path} did not parse to a mapping")
    return load_config_dict(raw, overrides=overrides, env=env)
