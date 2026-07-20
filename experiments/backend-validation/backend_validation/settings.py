"""Typed settings for the experiment: no hardcoded values, secrets stay in the environment.

The loader is a deliberate miniature of ``src/eval_harness/config/__init__.py`` (same
``${VAR}`` / ``${VAR:-default}`` interpolation and dotted-override idioms) rather than an
import of it: the L1 capability layer must not depend on the harness (spec finding R1).
Credentials never appear here — ``BackendSpec`` carries env-var *names*, resolved only at
the SDK boundary by the client factory.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

_ENV_PATTERN = re.compile(r"\$\{(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?::-(?P<default>[^}]*))?\}")


class SettingsError(ValueError):
    """Raised for malformed configuration; callers convert it to exit code 2."""


class TimeoutSpec(BaseModel):
    """Per-operation and per-probe time budgets (seconds)."""

    model_config = ConfigDict(extra="forbid")

    op_seconds: float = Field(gt=0)
    probe_budget_seconds: float = Field(gt=0)


class RetrySpec(BaseModel):
    """Retry policy for idempotent operations only; writes are never retried."""

    model_config = ConfigDict(extra="forbid")

    max_attempts: int = Field(ge=1)
    backoff_base_seconds: float = Field(ge=0)  # deterministic exponential, no jitter


class JudgeSpec(BaseModel):
    """The pinned local judge every judge-class probe uses, identical across backends."""

    model_config = ConfigDict(extra="forbid")

    base_url: str
    model: str
    api_key_env: str  # env var NAME; many OpenAI-compatible servers accept any value


class AirgapSpec(BaseModel):
    """Dual-scoring env matrices: as-shipped vs documented telemetry opt-out (R8)."""

    model_config = ConfigDict(extra="forbid")

    as_shipped_env: dict[str, str] = Field(default_factory=dict)
    opt_out_env: dict[str, str] = Field(default_factory=dict)


class BackendSpec(BaseModel):
    """One backend under test. Adding a backend (e.g. MLflow, R10) is a config entry."""

    model_config = ConfigDict(extra="forbid")

    id: str
    display_name: str
    base_url: str
    compose_file: str  # relative to the subtree root
    sdk_extra: str  # pip extra that installs this backend's SDK
    credential_env: dict[str, str] = Field(default_factory=dict)  # role -> env var NAME
    airgap: AirgapSpec = Field(default_factory=AirgapSpec)

    @field_validator("id")
    @classmethod
    def _id_is_slug(cls, value: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", value):
            raise ValueError(f"backend id must be a lowercase slug, got {value!r}")
        return value

    @field_validator("credential_env")
    @classmethod
    def _env_names_not_values(cls, value: dict[str, str]) -> dict[str, str]:
        for role, name in value.items():
            # A value with lowercase letters or '://' smells like a literal secret/URL,
            # not an env-var NAME — refuse loudly (leaked-key precedent in repo history).
            if not re.fullmatch(r"[A-Z][A-Z0-9_]*", name):
                raise ValueError(f"credential_env[{role!r}] must be an ENV VAR NAME, got {name!r}")
        return value


class Settings(BaseModel):
    """Root settings object; loaded from config.yaml, never constructed from literals."""

    model_config = ConfigDict(extra="forbid")

    backends: list[BackendSpec]
    judge: JudgeSpec
    timeouts: TimeoutSpec
    retries: RetrySpec
    artifacts_dir: str
    reports_dir: str
    min_free_gb: int = Field(ge=0)
    control_endpoint: str  # synthetic negative-control target; must be unroutable
    required_ports: list[int] = Field(default_factory=list)

    def backend(self, backend_id: str) -> BackendSpec:
        for spec in self.backends:
            if spec.id == backend_id:
                return spec
        known = ", ".join(spec.id for spec in self.backends)
        raise SettingsError(f"unknown backend {backend_id!r} (configured: {known})")

    def resolve_dir(self, name: str, base: Path) -> Path:
        """Resolve ``artifacts_dir``/``reports_dir`` under ``base`` (the subtree root).

        Zero-writes-outside-the-subtree is an invariant (spec R7), so a configured
        output path that escapes ``base`` is a configuration ERROR, not a preference.
        """
        raw = str(getattr(self, name))
        resolved = (base / raw).resolve()
        if not resolved.is_relative_to(base.resolve()):
            raise SettingsError(f"{name}={raw!r} escapes the experiment subtree {base}")
        return resolved


def interpolate(value: Any, env: Mapping[str, str]) -> Any:
    """Substitute ``${VAR}`` / ``${VAR:-default}`` recursively (eval_harness idiom)."""
    if isinstance(value, str):
        return _interpolate_str(value, env)
    if isinstance(value, list):
        return [interpolate(item, env) for item in value]
    if isinstance(value, dict):
        return {key: interpolate(item, env) for key, item in value.items()}
    return value


def _interpolate_str(text: str, env: Mapping[str, str]) -> str:
    def _replace(match: re.Match[str]) -> str:
        name = match.group("name")
        default = match.group("default")
        if name in env:
            return env[name]
        if default is not None:
            return default
        raise SettingsError(f"environment variable {name} is not set and has no default")

    return _ENV_PATTERN.sub(_replace, text)


def apply_overrides(data: dict[str, Any], overrides: Sequence[str]) -> dict[str, Any]:
    """Apply dotted ``key.path=value`` overrides (eval_harness idiom); values parse as YAML."""
    for override in overrides:
        key, sep, raw_value = override.partition("=")
        if not sep or not key:
            raise SettingsError(f"override must look like key.path=value, got {override!r}")
        cursor = data
        parts = key.split(".")
        for part in parts[:-1]:
            node = cursor.get(part)
            if not isinstance(node, dict):
                raise SettingsError(f"override path {key!r} does not exist in the config")
            cursor = node
        if parts[-1] not in cursor:
            raise SettingsError(f"override path {key!r} does not exist in the config")
        cursor[parts[-1]] = yaml.safe_load(raw_value)
    return data


def load_settings(
    path: Path,
    *,
    env: Mapping[str, str] | None = None,
    overrides: Sequence[str] = (),
) -> Settings:
    """Load, interpolate, override, and validate settings from ``path``."""
    if env is None:  # pragma: no cover - trivial default wiring
        env = os.environ
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SettingsError(f"cannot read settings file {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise SettingsError(f"settings file {path} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise SettingsError(f"settings file {path} must contain a mapping at the top level")
    data = apply_overrides(interpolate(raw, env), overrides)
    try:
        return Settings.model_validate(data)
    except ValidationError as exc:
        raise SettingsError(f"settings file {path} failed validation: {exc}") from exc
