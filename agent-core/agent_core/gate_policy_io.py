"""Resolve :class:`GatePolicyConfig` from file, env, and CLI without restating defaults.

Later sources win: dataclass defaults -> JSON ``--policy-file`` -> env overlay ->
explicit CLI flags. Empty env values are ignored so GitHub ``vars.*`` pass-through
stays inert until a human sets a repo variable (ADR 0029 / I-4).

``protected_auto_merge`` is refused from every operator seam -- same invariant as
the CLI flag being absent.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from .config import ConfigError
from .logging_util import debug_span, get_logger
from .merge_gate import GatePolicyConfig

logger = get_logger(__name__)

#: Fields an operator may overlay. Kept as a tuple of names so tests can lockstep
#: this module against :class:`GatePolicyConfig` without restating defaults.
OPERATOR_FIELDS: tuple[str, ...] = (
    "risk_target",
    "risk_ci_z",
    "min_calibration_n",
    "max_ece",
    "min_auroc",
    "max_bin_ci_width",
    "n_bins",
    "wilson_floor",
    "wilson_z",
)

_INT_FIELDS: frozenset[str] = frozenset({"min_calibration_n", "n_bins"})
_REFUSED_FIELDS: frozenset[str] = frozenset({"protected_auto_merge"})


@dataclass(frozen=True)
class GatePolicyIOConfig:
    """Names of the env-var overlay seam. Prefix is documented, not hardcoded at use."""

    env_prefix: str = "MERGE_GATE_"
    policy_file_env_var: str = "MERGE_GATE_POLICY_FILE"


def env_name(field: str, cfg: GatePolicyIOConfig | None = None) -> str:
    """``risk_target`` -> ``MERGE_GATE_RISK_TARGET`` (prefix from config)."""
    prefix = (cfg or GatePolicyIOConfig()).env_prefix
    return f"{prefix}{field.upper()}"


def _parse_field(name: str, raw: object) -> float | int:
    if name in _INT_FIELDS:
        if isinstance(raw, bool) or not isinstance(raw, int):
            # bool is an int subclass; refuse it. JSON numbers without a fraction
            # arrive as int; CLI strings are parsed by argparse before we get here.
            try:
                if isinstance(raw, str) or (isinstance(raw, float) and raw.is_integer()):
                    raw = int(raw)
                else:
                    raise TypeError
            except (TypeError, ValueError) as exc:
                raise ConfigError(f"merge-gate.{name} must be an int (got {raw!r})") from exc
        return int(raw)
    try:
        return float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"merge-gate.{name} must be a float (got {raw!r})") from exc


def _as_overlay(raw: Mapping[str, Any], *, source: str) -> dict[str, float | int]:
    unknown = sorted(k for k in raw if k not in OPERATOR_FIELDS and k not in _REFUSED_FIELDS)
    refused = sorted(k for k in raw if k in _REFUSED_FIELDS)
    if refused:
        raise ConfigError(
            f"{source} sets {refused} -- protected_auto_merge is not an operator knob "
            "(ADR 0005; withheld from CLI/env/file)"
        )
    if unknown:
        raise ConfigError(f"{source} has unknown gate-policy key(s): {unknown}")
    return {k: _parse_field(k, raw[k]) for k in OPERATOR_FIELDS if k in raw}


def load_policy_file(path: str | Path) -> dict[str, float | int]:
    """Strict JSON object of operator fields. Unknown keys raise :class:`ConfigError`."""
    text = Path(path).read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"policy file {path} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ConfigError(f"policy file {path} must be a JSON object, got {type(payload).__name__}")
    return _as_overlay(payload, source=f"policy file {path}")


def overlay_from_environ(
    environ: Mapping[str, str],
    cfg: GatePolicyIOConfig | None = None,
) -> dict[str, float | int]:
    """Non-empty ``MERGE_GATE_*`` values become an overlay; empty/unset are skipped."""
    io = cfg or GatePolicyIOConfig()
    raw: dict[str, Any] = {}
    for name in OPERATOR_FIELDS:
        value = environ.get(env_name(name, io), "")
        if value.strip():
            raw[name] = value.strip()
    refused = environ.get(env_name("protected_auto_merge", io), "").strip()
    if refused:
        raw["protected_auto_merge"] = refused
    if not raw:
        return {}
    return _as_overlay(raw, source="environment")


def resolve_policy(
    *,
    cli: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
    file_values: Mapping[str, float | int] | None = None,
    io_cfg: GatePolicyIOConfig | None = None,
    base: GatePolicyConfig | None = None,
) -> GatePolicyConfig:
    """Build a policy. ``None``/missing CLI values mean "not set", not 0.0.

    ``base`` defaults to :class:`GatePolicyConfig` so callers never retype field
    defaults. :class:`GatePolicyConfig.__post_init__` still validates the result.
    """
    io = io_cfg or GatePolicyIOConfig()
    current: dict[str, Any] = {
        f.name: getattr(base or GatePolicyConfig(), f.name)
        for f in fields(GatePolicyConfig)
        if f.name != "protected_auto_merge"
    }
    with debug_span(logger, "resolve_policy"):
        if file_values:
            current.update(file_values)
            logger.info("merge-gate policy overlay from file: %s", sorted(file_values))
        env_overlay = overlay_from_environ(environ or {}, io)
        if env_overlay:
            current.update(env_overlay)
            logger.info("merge-gate policy overlay from env: %s", sorted(env_overlay))
        if cli:
            explicit = {k: v for k, v in cli.items() if k in OPERATOR_FIELDS and v is not None}
            if explicit:
                parsed = {k: _parse_field(k, v) for k, v in explicit.items()}
                current.update(parsed)
                logger.info("merge-gate policy overlay from CLI: %s", sorted(parsed))
    return GatePolicyConfig(**current)
