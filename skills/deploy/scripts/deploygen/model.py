"""Deployment configuration for the generated ``deploy.sh`` scaffold.

Config-driven, not detected: the deployment target (app, artifact, health URL, environment)
comes from the user via flags, and every value lands in the script as a ``${VAR:-default}``
override so **secrets are never inlined** — they are read from the environment at run time
(ADR-0009 baseline: no hard-coded secrets, config-driven defaults).

Unset critical values default to ``<...>`` placeholders; the generated script's ``require``
guard fails fast on any placeholder still present at run time, so a half-configured deploy
aborts instead of doing something surprising.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DeployConfig:
    """Values substituted into the deploy script's overridable variable block."""

    app: str = "app"
    environment: str = "production"
    artifact: str = "<artifact>"
    health_url: str = "<health-url>"
