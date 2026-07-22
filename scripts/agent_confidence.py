#!/usr/bin/env python3
"""Agent identity + deterministic confidence proxy for merge-gate seeding (F-042, ADR 0023).

Two responsibilities, both pure and offline:

  * **Identity** — is a merged change agent-authored, and by which agent?
    Resolved from the PR head-branch prefix (and optionally the author login) via
    ``config/agent-authors.yaml``. Routing is on the head-ref prefix, not the author
    login, which is uniform for agent and human PRs in this repo (ADR 0023 Context).
  * **Confidence proxy** — a varying ``raw_confidence`` in the open interval (0, 1)
    computed deterministically from merge-time signals (diff size, files touched,
    test-file ratio, protected-path touch) with weights in ``config/agent-confidence.yaml``.
    It is a transparent heuristic, NOT an agent's real confidence (ADR 0023 §1); its only
    job is to make the calibration corpus non-degenerate.

The same ``compute_confidence`` runs live at merge time (this CLI, driven by
``merge-gate-seed.yml``) and retroactively during the F-044 backfill, so forward and
migrated rows are computed identically.

CLI (consumed by the seed workflow)::

    python scripts/agent_confidence.py --files-from changed.z --lines-changed 137 \
        --head-ref claude/foo --author-login ianshank [--output out.json]

emits ``{"agent": true, "agent_version": "claude-code", "confidence": 0.83}`` for an
agent change, or ``{"agent": false, "agent_version": null, "confidence": null}`` otherwise.

Exit codes:
    0 - JSON written (agent or not)
    2 - configuration error (unreadable/invalid config, undeterminable file set)
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass

import yaml
from _cli import configure_logging
from check_protected_changes import ConfigError

# Reuse the repo's single source of glob semantics + protected-path classification,
# exactly as scripts/merge_gate_context.py does — no second spelling of either.
from eval_protected_paths import _glob_to_regex, matched_protected

logger = logging.getLogger(__name__)

DEFAULT_IDENTITY_PATH = os.path.join("config", "agent-authors.yaml")
DEFAULT_PROXY_PATH = os.path.join("config", "agent-confidence.yaml")
SUPPORTED_SCHEMA_MAJOR = "1"

EXIT_OK = 0
EXIT_CONFIG = 2

_PROXY_KEYS = frozenset(
    {
        "base",
        "w_size",
        "w_files",
        "w_tests",
        "w_protected",
        "size_scale",
        "size_cap",
        "files_scale",
        "files_cap",
        "clamp_lo",
        "clamp_hi",
    }
)


def _require_major(version: str, path: str) -> None:
    if version.split(".", 1)[0] != SUPPORTED_SCHEMA_MAJOR:
        raise ConfigError(
            f"unsupported schema_version {version!r} in '{path}' (supported major: {SUPPORTED_SCHEMA_MAJOR}.x)"
        )


def _load_yaml(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            doc = yaml.safe_load(fh)
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"cannot read config '{path}': {exc}") from exc
    if not isinstance(doc, dict):
        raise ConfigError(f"config '{path}' must be a mapping")
    return doc


# --- identity ----------------------------------------------------------------
@dataclass(frozen=True)
class AgentRule:
    agent_version: str
    branch_prefixes: tuple[str, ...]
    author_logins: tuple[str, ...]

    def matches(self, head_ref: str, author_login: str) -> bool:
        if head_ref and any(head_ref.startswith(p) for p in self.branch_prefixes):
            return True
        return bool(author_login) and author_login in self.author_logins


@dataclass(frozen=True)
class AgentIdentity:
    """Strictly-validated agent-identification rules (first match wins, file order)."""

    schema_version: str
    agents: tuple[AgentRule, ...]

    @staticmethod
    def load(path: str = DEFAULT_IDENTITY_PATH) -> AgentIdentity:
        doc = _load_yaml(path)
        if set(doc) != {"schema_version", "agents"}:
            raise ConfigError(f"agent-authors keys must be exactly ['agents', 'schema_version']; got {sorted(doc)}")
        _require_major(str(doc["schema_version"]), path)
        raw_agents = doc["agents"]
        if not isinstance(raw_agents, list) or not raw_agents:
            raise ConfigError("agents must be a non-empty list")
        agents: list[AgentRule] = []
        seen: set[str] = set()
        for i, raw in enumerate(raw_agents):
            if not isinstance(raw, dict) or set(raw) != {"agent_version", "branch_prefixes", "author_logins"}:
                raise ConfigError(
                    f"agents[{i}] must have exactly the keys agent_version, branch_prefixes, author_logins"
                )
            version = str(raw["agent_version"])
            if not version:
                raise ConfigError(f"agents[{i}].agent_version must be non-empty")
            if version in seen:
                raise ConfigError(f"duplicate agent_version {version!r}")
            seen.add(version)
            prefixes = _str_list(raw["branch_prefixes"], f"agents[{i}].branch_prefixes")
            logins = _str_list(raw["author_logins"], f"agents[{i}].author_logins")
            if not prefixes and not logins:
                raise ConfigError(f"agents[{i}] ({version}) must list at least one branch_prefix or author_login")
            agents.append(AgentRule(version, tuple(prefixes), tuple(logins)))
        return AgentIdentity(str(doc["schema_version"]), tuple(agents))

    def resolve(self, head_ref: str, author_login: str) -> str | None:
        """Return the agent_version of the first matching rule, or None (human)."""
        for rule in self.agents:
            if rule.matches(head_ref, author_login):
                return rule.agent_version
        return None


def _str_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"{label} must be a list of strings")
    return [v for v in value if v]


# --- confidence proxy --------------------------------------------------------
@dataclass(frozen=True)
class ProxyConfig:
    base: float
    w_size: float
    w_files: float
    w_tests: float
    w_protected: float
    size_scale: float
    size_cap: float
    files_scale: float
    files_cap: float
    clamp_lo: float
    clamp_hi: float
    test_globs: tuple[str, ...]

    @staticmethod
    def load(path: str = DEFAULT_PROXY_PATH) -> ProxyConfig:
        doc = _load_yaml(path)
        if set(doc) != {"schema_version", "proxy", "test_globs"}:
            raise ConfigError(
                f"agent-confidence keys must be exactly ['proxy', 'schema_version', 'test_globs']; got {sorted(doc)}"
            )
        _require_major(str(doc["schema_version"]), path)
        proxy = doc["proxy"]
        if not isinstance(proxy, dict) or set(proxy) != _PROXY_KEYS:
            raise ConfigError(f"proxy must have exactly the keys {sorted(_PROXY_KEYS)}")
        vals: dict[str, float] = {}
        for k in _PROXY_KEYS:
            try:
                vals[k] = float(proxy[k])
            except (TypeError, ValueError) as exc:
                raise ConfigError(f"proxy.{k} must be a number") from exc
        for k in ("size_scale", "files_scale", "size_cap", "files_cap"):
            if vals[k] <= 0:
                raise ConfigError(f"proxy.{k} must be > 0")
        if not (0.0 < vals["clamp_lo"] < vals["clamp_hi"] < 1.0):
            raise ConfigError("proxy requires 0 < clamp_lo < clamp_hi < 1 (confidence stays strictly inside (0,1))")
        globs = _str_list(doc["test_globs"], "test_globs")
        if not globs:
            raise ConfigError("test_globs must be a non-empty list of strings")
        return ProxyConfig(test_globs=tuple(globs), **vals)


def _test_ratio(files: Sequence[str], test_globs: Sequence[str]) -> float:
    if not files:
        return 0.0
    regexes = [_glob_to_regex(g) for g in test_globs]
    n_tests = sum(1 for f in files if any(r.match(f) for r in regexes))
    return n_tests / len(files)


def compute_confidence(files: Sequence[str], lines_changed: int, cfg: ProxyConfig) -> float:
    """Deterministic proxy confidence in (clamp_lo, clamp_hi) ⊂ (0, 1).

    Pure: identical output for identical (files, lines_changed, cfg), whether run live
    at merge time or retroactively over a historical diff (F-044).
    """
    n_files = len(files)
    size_norm = min(max(lines_changed, 0) / cfg.size_scale, cfg.size_cap)
    files_norm = min(n_files / cfg.files_scale, cfg.files_cap)
    test_ratio = _test_ratio(files, cfg.test_globs)
    protected = 1.0 if matched_protected(list(files)) else 0.0
    z = (
        cfg.base
        - cfg.w_size * size_norm
        - cfg.w_files * files_norm
        + cfg.w_tests * test_ratio
        - cfg.w_protected * protected
    )
    raw = 1.0 / (1.0 + math.exp(-z))
    clamped = min(max(raw, cfg.clamp_lo), cfg.clamp_hi)
    return round(clamped, 6)


# --- file resolution + CLI ---------------------------------------------------
def _read_nul_delimited(path: str) -> list[str]:
    try:
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
    except OSError as exc:
        raise ConfigError(f"cannot read --files-from '{path}': {exc}") from exc
    return [f for f in raw.split("\0") if f.strip()]


def resolve_files(args: argparse.Namespace) -> list[str]:
    if args.files:
        return [f for f in args.files if f.strip()]
    if args.files_from:
        return _read_nul_delimited(args.files_from)
    return []


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Resolve agent identity + confidence proxy for seeding.")
    source = ap.add_mutually_exclusive_group()
    source.add_argument("--files", nargs="+", help="explicit changed-file list")
    source.add_argument("--files-from", help="NUL-delimited changed-file list (git diff --name-only -z)")
    ap.add_argument("--lines-changed", type=int, default=0, help="added+removed lines (git diff --numstat)")
    ap.add_argument("--head-ref", default="", help="PR head branch ref (e.g. claude/foo)")
    ap.add_argument("--author-login", default="", help="PR author login")
    ap.add_argument("--identity-config", default=DEFAULT_IDENTITY_PATH)
    ap.add_argument("--proxy-config", default=DEFAULT_PROXY_PATH)
    ap.add_argument("--output", help="write JSON here instead of stdout")
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging()
    try:
        identity = AgentIdentity.load(args.identity_config)
        agent_version = identity.resolve(args.head_ref, args.author_login)
        if agent_version is None:
            result: dict[str, object] = {"agent": False, "agent_version": None, "confidence": None}
        else:
            proxy = ProxyConfig.load(args.proxy_config)
            files = resolve_files(args)
            confidence = compute_confidence(files, args.lines_changed, proxy)
            result = {"agent": True, "agent_version": agent_version, "confidence": confidence}
    except ConfigError as exc:
        logger.error("agent-confidence: %s", exc)
        return EXIT_CONFIG
    payload = json.dumps(result, sort_keys=True)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(payload + "\n")
    else:
        print(payload)
    logger.info(
        "agent-confidence: agent=%s agent_version=%s confidence=%s head_ref=%s",
        result["agent"],
        result["agent_version"],
        result["confidence"],
        args.head_ref or "(none)",
    )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
