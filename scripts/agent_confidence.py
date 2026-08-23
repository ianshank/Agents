#!/usr/bin/env python3
"""Agent identity + deterministic confidence proxy for merge-gate seeding (F-042, ADR 0023).

Two responsibilities, both pure and offline:

  * **Identity** — is a merged change agent-authored, and by which agent?
    Resolved from the PR head-branch prefix (and optionally the author login) via
    ``config/agent-authors.yaml``. Routing is on the head-ref prefix, not the author
    login, which is uniform for agent and human PRs in this repo (ADR 0023 Context).
  * **Confidence proxy** — a varying ``raw_confidence`` in the open interval (0, 1)
    computed deterministically from merge-time signals (diff size, files touched,
    test-file ratio, and a protected-path touch that EXCLUDES newly added test files --
    F-061) with weights in ``config/agent-confidence.yaml``.
    It is a transparent heuristic, NOT an agent's real confidence (ADR 0023 §1); its only
    job is to make the calibration corpus non-degenerate.

The same ``compute_confidence`` runs live at merge time (this CLI, driven by
``merge-gate-seed.yml``) and retroactively during the F-044 backfill, so forward and
migrated rows are computed identically.

CLI (consumed by the seed workflow)::

    python scripts/agent_confidence.py --files-from changed.z --added-from added.z \
        --lines-changed 137 --head-ref claude/foo --author-login ianshank \
        [--output out.json] [-v]

``--files``/``--files-from`` give the changed set; ``--added``/``--added-from`` give the
subset the change newly created (``git diff --name-only -z --diff-filter=A``). Omitting BOTH
added flags means "additions unknown" and reproduces the pre-F-061 protected-path result --
an empty ``--added-from`` file means "known, and nothing was added", which is different.
``-v`` raises logging to DEBUG and prints the full score decomposition.

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
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from _cli import configure_logging
from _config import (
    ConfigError,
    load_yaml_mapping,
    require_exact_keys,
    require_major,
    resolve_explicit_files,
)

# Reuse the repo's single source of glob semantics + protected-path classification,
# exactly as scripts/merge_gate_context.py does — no second spelling of either.
from eval_protected_paths import _glob_to_regex, _normalise, matched_protected

logger = logging.getLogger(__name__)

DEFAULT_IDENTITY_PATH = os.path.join("config", "agent-authors.yaml")
DEFAULT_PROXY_PATH = os.path.join("config", "agent-confidence.yaml")

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
        doc = load_yaml_mapping(path)
        require_exact_keys(doc, {"schema_version", "agents"}, "agent-authors")
        require_major(str(doc["schema_version"]), path)
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
        doc = load_yaml_mapping(path)
        require_exact_keys(doc, {"schema_version", "proxy", "test_globs"}, "agent-confidence")
        require_major(str(doc["schema_version"]), path)
        proxy = doc["proxy"]
        if not isinstance(proxy, dict):
            raise ConfigError("agent-confidence proxy must be a mapping")
        require_exact_keys(proxy, _PROXY_KEYS, "proxy")
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


def _test_regexes(test_globs: Sequence[str]) -> list[re.Pattern[str]]:
    """Compile the configured test globs once per call site."""
    return [_glob_to_regex(g) for g in test_globs]


def _is_test(path: str, regexes: Sequence[re.Pattern[str]]) -> bool:
    """True when *path* matches any configured test glob.

    The single spelling of "is this a test file". ``_test_ratio`` and the added-test filter
    in ``compute_confidence`` both route through here so the two signals can never disagree
    about what a test is.

    The path is normalised first, matching what ``matched_protected`` does internally. Without
    it the two halves of the same function disagree on spelling: ``./tests/conftest.py`` counts
    as an eval-protected path but not as a test, so it takes the protected penalty *and*
    contributes nothing to ``test_ratio``.
    """
    norm = _normalise(path)
    return any(r.match(norm) for r in regexes)


def _test_ratio(files: Sequence[str], test_globs: Sequence[str]) -> float:
    if not files:
        return 0.0
    regexes = _test_regexes(test_globs)
    n_tests = sum(1 for f in files if _is_test(f, regexes))
    return n_tests / len(files)


def _protected_inputs(files: Sequence[str], added: Sequence[str] | None, cfg: ProxyConfig) -> list[str]:
    """The file subset the protected-path signal is computed over.

    A **newly added** test file is withheld. Every ``tests/**`` root is an eval-protected
    path, so without this a test file is counted twice: once as ``+w_tests * test_ratio`` and
    again as ``-w_protected``, a net penalty for adding tests. A *modified* test still feeds
    the signal, because weakening an existing eval-defining test is exactly the eval-surface
    risk the protected term exists to price.

    ``added is None`` means the caller could not distinguish additions from modifications.
    It is treated as the empty set, which is the same arithmetic -- withholding nothing is a
    no-op -- so the pre-F-061 result is reproduced either way. The two are kept distinct in
    the *type* because they are different facts about the caller, not because they currently
    score differently; do not write a test asserting a behavioural difference between them.

    Spelling is not significant on either side: ``_is_test`` normalises internally and the
    comparison keys are normalised, matching what ``matched_protected`` already does. Without
    that, ``./tests/conftest.py`` or a backslash spelling would be protected but unrecognised
    as a test -- silently disabling the withholding for that file.
    """
    regexes = _test_regexes(cfg.test_globs)
    added_tests = {_normalise(f) for f in (added or ()) if _is_test(f, regexes)}
    return [f for f in files if _normalise(f) not in added_tests]


def _log_score(
    cfg: ProxyConfig,
    result: float,
    *,
    clamped: float,
    raw: float,
    z: float,
    n_files: int,
    size_norm: float,
    files_norm: float,
    test_ratio: float,
    protected: float,
    protected_hits: Sequence[str],
) -> None:
    """Emit the score decomposition (DEBUG) and any clamp saturation (INFO).

    Kept out of ``compute_confidence`` so that function stays inside the 50-line budget and
    reads as pure arithmetic. A surprising score is otherwise only explicable by re-deriving
    it by hand -- which is how a two-month floor saturation went unnoticed.
    """
    logger.debug(
        "agent-confidence: n_files=%d size_norm=%.4f files_norm=%.4f test_ratio=%.4f "
        "protected=%.1f z=%.4f raw=%.6f -> %.6f",
        n_files,
        size_norm,
        files_norm,
        test_ratio,
        protected,
        z,
        raw,
        result,
    )
    if protected_hits:
        # matched_protected returns the matched paths, not a bool -- so naming them is free.
        logger.debug("agent-confidence: protected paths driving the penalty: %s", ", ".join(protected_hits))
    # Saturation is invisible in one score but fatal in aggregate: a corpus pinned to a rail
    # carries no information for calibration. Surface it per-run rather than only at audit.
    # Compare the CLAMPED value, not the rounded one: round(clamped, 6) != clamp_lo whenever a
    # bound carries more than six decimals, which would silently switch this detector off.
    if clamped in (cfg.clamp_lo, cfg.clamp_hi):
        rail = "clamp_lo" if clamped == cfg.clamp_lo else "clamp_hi"
        logger.info("agent-confidence: score saturated at %s=%.6g (raw=%.6f)", rail, clamped, raw)


def compute_confidence(
    files: Sequence[str],
    lines_changed: int,
    cfg: ProxyConfig,
    *,
    added: Sequence[str] | None = None,
) -> float:
    """Deterministic proxy confidence in (clamp_lo, clamp_hi) ⊂ (0, 1).

    Pure: identical output for identical inputs, live at merge time or retroactively over a
    historical diff (F-044). ``added`` is the subset of *files* the change newly created --
    see ``_protected_inputs``.
    """
    n_files = len(files)
    size_norm = min(max(lines_changed, 0) / cfg.size_scale, cfg.size_cap)
    files_norm = min(n_files / cfg.files_scale, cfg.files_cap)
    test_ratio = _test_ratio(files, cfg.test_globs)
    protected_inputs = _protected_inputs(files, added, cfg)
    protected_hits = matched_protected(protected_inputs)
    protected = 1.0 if protected_hits else 0.0
    z = (
        cfg.base
        - cfg.w_size * size_norm
        - cfg.w_files * files_norm
        + cfg.w_tests * test_ratio
        - cfg.w_protected * protected
    )
    # Clamp z to a numerically-safe range before exp(). The LOWER bound is load-bearing: a
    # large-negative z makes exp(-z)=exp(+big) OverflowError. The upper bound is defensive
    # symmetry only (a large-positive z makes exp(-z) underflow to 0.0, which is harmless), kept
    # so the guard stays correct if the sigmoid form is ever changed. Output is clamped to
    # (clamp_lo, clamp_hi) regardless, so neither bound alters an observable result.
    z = max(-700.0, min(700.0, z))
    raw = 1.0 / (1.0 + math.exp(-z))
    clamped = min(max(raw, cfg.clamp_lo), cfg.clamp_hi)
    result = round(clamped, 6)
    _log_score(
        cfg,
        result,
        clamped=clamped,
        raw=raw,
        z=z,
        n_files=n_files,
        size_norm=size_norm,
        files_norm=files_norm,
        test_ratio=test_ratio,
        protected=protected,
        protected_hits=protected_hits,
    )
    return result


# --- file resolution + CLI ---------------------------------------------------
def resolve_files(args: argparse.Namespace) -> list[str]:
    """Changed files from --files / --files-from; empty list when neither is given."""
    explicit: list[str] | None = resolve_explicit_files(args.files, args.files_from)
    return explicit if explicit is not None else []


def resolve_added(args: argparse.Namespace) -> list[str] | None:
    """Newly-added files from --added / --added-from, or ``None`` when neither is given.

    ``None`` is meaningful and is NOT the same as ``[]``: it means the caller could not tell
    additions from modifications, so ``compute_confidence`` keeps its pre-F-061 behaviour.
    An empty list means "known, and this change added nothing".
    """
    explicit: list[str] | None = resolve_explicit_files(args.added, args.added_from, flag="--added-from")
    return explicit


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Resolve agent identity + confidence proxy for seeding.")
    source = ap.add_mutually_exclusive_group()
    source.add_argument("--files", nargs="+", help="explicit changed-file list")
    source.add_argument("--files-from", help="NUL-delimited changed-file list (git diff --name-only -z)")
    added = ap.add_mutually_exclusive_group()
    added.add_argument("--added", nargs="+", help="explicit newly-added-file list")
    added.add_argument(
        "--added-from",
        help="NUL-delimited newly-added-file list (git diff --name-only -z --diff-filter=A); "
        "omitting both leaves additions unknown and keeps the pre-F-061 protected-path result",
    )
    ap.add_argument("--lines-changed", type=int, default=0, help="added+removed lines (git diff --numstat)")
    ap.add_argument("--head-ref", default="", help="PR head branch ref (e.g. claude/foo)")
    ap.add_argument("--author-login", default="", help="PR author login")
    ap.add_argument("--identity-config", default=DEFAULT_IDENTITY_PATH)
    ap.add_argument("--proxy-config", default=DEFAULT_PROXY_PATH)
    ap.add_argument("--output", help="write JSON here instead of stdout")
    ap.add_argument("-v", "--verbose", action="store_true", help="Enable DEBUG logging")
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.verbose)
    try:
        identity = AgentIdentity.load(args.identity_config)
        agent_version = identity.resolve(args.head_ref, args.author_login)
        if agent_version is None:
            result: dict[str, object] = {"agent": False, "agent_version": None, "confidence": None}
        else:
            proxy = ProxyConfig.load(args.proxy_config)
            files = resolve_files(args)
            if not files:
                # An agent change with no resolvable files would score all-zero signals — a
                # misleading confidence. Treat it as an undeterminable file set (exit 2); the
                # seed workflow's fail-safe then routes the merge to the human lane. Name the
                # inputs so an operator can tell an empty diff from a bad --files-from path.
                raise ConfigError(
                    "no changed files resolved for an agent change (undeterminable file set; "
                    f"head_ref={args.head_ref or '(none)'}, files-from={args.files_from or '(none)'})"
                )
            confidence = compute_confidence(files, args.lines_changed, proxy, added=resolve_added(args))
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
