"""deploygen - deterministic deployment-script generation.

``render_deploy(config)`` turns a :class:`DeployConfig` into a byte-stable, ShellCheck-clean
``deploy.sh`` safety scaffold (strict mode, dry-run, confirmation gate, rollback, health check).
"""

from __future__ import annotations

from .model import DeployConfig
from .render import render_deploy

__all__ = ["DeployConfig", "render_deploy"]
