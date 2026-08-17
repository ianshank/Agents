"""Detect whether ``spec-guardian``/``peer-reviewer`` are dispatchable, honestly.

``claude-foundation/`` is a **staging** directory (ADR 0028), not an installed plugin in this
repo's own sessions. Its two charter files being present on disk therefore proves the charters
exist to *stage* — it does not prove they are *loaded* into whatever session is running this
skill. Conflating those two facts is exactly the failure mode this module exists to avoid.

What this module actually checks, and is honest about the limits of:

1. **Necessary, file-system-checkable facts** — do both charter files exist, and does
   ``claude-foundation/.claude-plugin/plugin.json`` look like a real plugin manifest. Absence
   of either is conclusive: the plugin path cannot be available.
2. **A real but narrow environment signal** — ``CLAUDE_PLUGIN_ROOT`` is the environment
   variable Claude Code populates for a plugin's own hooks/scripts while they run (see
   ``claude-foundation/hooks/hooks.json``, which reads it directly). If it is set and resolves
   to this same staging directory, that is genuine evidence this process is executing *as*
   the foundation plugin. It is not, however, evidence about an arbitrary *other* subprocess
   the calling agent might run via its own shell tool — that variable is scoped to the
   plugin's own invocation, not exported session-wide. This module therefore reports what it
   found, never upgrades a filesystem coincidence into a plugin-loaded claim, and its default
   recommendation is conservative: "degraded" unless the environment signal is actually there.

Presence alone is never sufficient. The docstring for :func:`detect_dispatch_path` states the
resulting recommendation must still be corroborated by the calling agent checking its own
actually-available subagent types before it dispatches ``spec-guardian``/``peer-reviewer`` by
name — this module cannot see that from a subprocess, and does not pretend to.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

DispatchPath = Literal["plugin", "degraded"]
Confidence = Literal["low", "medium"]

#: Env var Claude Code populates for a plugin's own hook/script invocations
#: (see claude-foundation/hooks/hooks.json, which reads it directly).
PLUGIN_ROOT_ENV_VAR = "CLAUDE_PLUGIN_ROOT"

_CHARTER_NAMES: tuple[str, ...] = ("spec-guardian.md", "peer-reviewer.md")
_EXPECTED_PLUGIN_NAME = "foundation"


@dataclass(frozen=True)
class DispatchDetection:
    """Everything this process could actually check, plus the conservative recommendation."""

    charters_present: bool
    plugin_manifest_present: bool
    claude_plugin_root: str | None
    env_signals_plugin_loaded: bool
    recommended_path: DispatchPath
    confidence: Confidence
    reason: str


def _charters_present(repo_root: Path) -> bool:
    agents_dir = repo_root / "claude-foundation" / "agents"
    return all((agents_dir / name).is_file() for name in _CHARTER_NAMES)


def _plugin_manifest_present(repo_root: Path) -> bool:
    manifest = repo_root / "claude-foundation" / ".claude-plugin" / "plugin.json"
    if not manifest.is_file():
        return False
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(data, dict) and data.get("name") == _EXPECTED_PLUGIN_NAME


def _env_signals_plugin_loaded(repo_root: Path, claude_plugin_root: str | None) -> bool:
    """True only if CLAUDE_PLUGIN_ROOT is set AND resolves to this repo's staging directory."""
    if not claude_plugin_root:
        return False
    foundation_dir = repo_root / "claude-foundation"
    try:
        return Path(claude_plugin_root).resolve() == foundation_dir.resolve()
    except OSError:
        return False
    except RuntimeError:
        # CPython's pathlib wraps a symlink loop (OSError/ELOOP) in a RuntimeError instead of
        # letting it propagate as an OSError -- verified empirically (Python 3.11), not
        # assumed from documentation. An unresolvable CLAUDE_PLUGIN_ROOT is exactly the "no
        # signal" case, not a crash.
        return False


def detect_dispatch_path(repo_root: Path, *, environ: dict[str, str] | None = None) -> DispatchDetection:
    """Best-effort, conservative detection of whether the plugin dispatch path is available.

    ``environ`` defaults to the real process environment; tests pass an explicit dict so the
    plugin-loaded branch is reachable without mutating global state. A caller (human or agent)
    that has independently confirmed ``spec-guardian``/``peer-reviewer`` appear among its own
    dispatchable subagent types may override this recommendation — see the CLI's
    ``--force-path`` flag — but this function itself never assumes that confirmation happened.
    """
    env = os.environ if environ is None else environ
    charters_present = _charters_present(repo_root)
    plugin_manifest_present = _plugin_manifest_present(repo_root)
    claude_plugin_root = env.get(PLUGIN_ROOT_ENV_VAR)
    env_signals = _env_signals_plugin_loaded(repo_root, claude_plugin_root)

    if not charters_present:
        return DispatchDetection(
            charters_present=False,
            plugin_manifest_present=plugin_manifest_present,
            claude_plugin_root=claude_plugin_root,
            env_signals_plugin_loaded=False,
            recommended_path="degraded",
            confidence="medium",
            reason=(
                "claude-foundation/agents/{spec-guardian,peer-reviewer}.md are not both present "
                "in this tree, so the plugin path cannot be available regardless of session "
                "state -- degrading to a general-purpose dispatch."
            ),
        )

    if env_signals:
        return DispatchDetection(
            charters_present=True,
            plugin_manifest_present=plugin_manifest_present,
            claude_plugin_root=claude_plugin_root,
            env_signals_plugin_loaded=True,
            recommended_path="plugin",
            confidence="medium",
            reason=(
                f"{PLUGIN_ROOT_ENV_VAR} is set and resolves to this repo's claude-foundation/ "
                "staging directory, which is real evidence this process is executing as the "
                "foundation plugin. Still corroborate before dispatching by name: confirm "
                "spec-guardian/peer-reviewer actually appear among your own available subagent "
                "types (this signal is necessary, not sufficient -- ADR 0028)."
            ),
        )

    return DispatchDetection(
        charters_present=True,
        plugin_manifest_present=plugin_manifest_present,
        claude_plugin_root=claude_plugin_root,
        env_signals_plugin_loaded=False,
        recommended_path="degraded",
        confidence="medium",
        reason=(
            "claude-foundation/ is staged in this tree (ADR 0028) but nothing observable from "
            "this process indicates the foundation plugin is loaded into the current session "
            f"({PLUGIN_ROOT_ENV_VAR} is "
            + (
                f"set to {claude_plugin_root!r} but does not resolve to claude-foundation/"
                if claude_plugin_root
                else "unset"
            )
            + "). Degrading to a general-purpose dispatch with the review method inlined. "
            "Files being staged on disk is not evidence they are loaded into this session -- "
            "if you have independently confirmed spec-guardian/peer-reviewer are among your "
            "own dispatchable subagent types, use --force-path=plugin to override."
        ),
    )
