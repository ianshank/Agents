#!/usr/bin/env python3
"""Compose the calibrated merge gate's ChangeContext JSON (F-035, ADR 0018).

Bridges CI facts to ``python -m agent_core.merge_gate_ci --context``:

  * ``mech_pass``          <- --mech-pass/--no-mech-pass (regression-gate result;
                              defaults to False — fail-safe toward REJECT-in-shadow)
  * ``touches_protected``  <- eval_protected_paths.matched_protected over the
                              changed-file set
  * ``domain``             <- first-match-wins rules in config/merge-gate-domains.yaml
  * ``raw_confidence``     <- --confidence (agent-reported), or 0.0; --human prefixes
                              the domain with the reserved namespace and forces 0.0,
                              keeping human outcomes out of agent-domain calibration

Changed files come from ``--files``, a NUL-delimited ``--files-from`` file
(produced with ``git diff --name-only -z`` — robust to odd filenames), or a live
``git diff`` against ``--base-ref``/``$BASE_REF``/origin/main.

Exit codes:
    0 - context written
    2 - configuration error (unreadable/invalid mapping, undeterminable file set)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
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
from agent_core.domains import HUMAN_NAMESPACE as CANONICAL_HUMAN_NAMESPACE
from check_protected_changes import DEFAULT_BASE_REF, changed_files_from_git

# _glob_to_regex is the repo's single source of glob semantics (anchored; `*`
# stays within one path segment). fnmatch would wrongly match `*` across
# separators, silently changing domain classification.
from eval_protected_paths import _glob_to_regex, matched_protected

logger = logging.getLogger(__name__)

DEFAULT_MAPPING_PATH = os.path.join("config", "merge-gate-domains.yaml")
_HUMAN_CONFIDENCE = 0.0  # ADR 0018 §5: human-authored changes carry no agent confidence

EXIT_OK = 0
EXIT_CONFIG = 2


@dataclass(frozen=True)
class DomainRule:
    pattern: str
    domain: str


@dataclass(frozen=True)
class DomainMapping:
    """Strictly-validated path->domain rules (first match wins, in file order)."""

    schema_version: str
    default_domain: str
    human_namespace: str
    rules: tuple[DomainRule, ...]

    @staticmethod
    def load(path: str) -> DomainMapping:
        doc = load_yaml_mapping(path)
        require_exact_keys(doc, {"schema_version", "default_domain", "human_namespace", "rules"}, "domain mapping")
        require_major(str(doc["schema_version"]), path)
        namespace = str(doc["human_namespace"])
        if not namespace.endswith("/"):
            raise ConfigError("human_namespace must end with '/'")
        # The YAML mirrors agent_core.domains.HUMAN_NAMESPACE; it is not an independent
        # override (agent_core classifies against the canonical literal). Enforce equality at
        # load so a drifted YAML fails loud here instead of silently poisoning the agent pool.
        if namespace != CANONICAL_HUMAN_NAMESPACE:
            raise ConfigError(
                f"human_namespace {namespace!r} must equal the canonical "
                f"agent_core.domains.HUMAN_NAMESPACE {CANONICAL_HUMAN_NAMESPACE!r} "
                "(the reserved namespace is single-sourced there; the YAML only mirrors it)"
            )
        raw_rules = doc["rules"]
        if not isinstance(raw_rules, list) or not raw_rules:
            raise ConfigError("rules must be a non-empty list")
        rules: list[DomainRule] = []
        for i, raw in enumerate(raw_rules):
            if not isinstance(raw, dict) or set(raw) != {"pattern", "domain"}:
                raise ConfigError(f"rules[{i}] must have exactly the keys pattern, domain")
            rules.append(DomainRule(pattern=str(raw["pattern"]), domain=str(raw["domain"])))
        for name in [str(doc["default_domain"]), *(r.domain for r in rules)]:
            if not name:
                raise ConfigError("domains must be non-empty")
            # The reserved namespace is applied only by the seed path; a mapping
            # that emitted it would leak human outcomes into gate lookups.
            if name.startswith(namespace):
                raise ConfigError(f"domain '{name}' must not use the reserved '{namespace}'")
        return DomainMapping(
            schema_version=str(doc["schema_version"]),
            default_domain=str(doc["default_domain"]),
            human_namespace=namespace,
            rules=tuple(rules),
        )


def classify_domain(files: Sequence[str], mapping: DomainMapping) -> str:
    """First rule (in file order) whose glob matches ANY changed file wins."""
    for rule in mapping.rules:
        regex = _glob_to_regex(rule.pattern)
        if any(regex.match(f) for f in files):
            return rule.domain
    return mapping.default_domain


def build_context(
    files: Sequence[str],
    mapping: DomainMapping,
    *,
    mech_pass: bool,
    human: bool,
    confidence: float | None,
) -> dict[str, object]:
    """The exact JSON shape merge_gate_ci._load_context consumes."""
    domain = classify_domain(files, mapping)
    if human:
        domain = mapping.human_namespace + domain
    raw_confidence = _HUMAN_CONFIDENCE if human or confidence is None else confidence
    return {
        "mech_pass": mech_pass,
        "touches_protected": bool(matched_protected(files)),
        "raw_confidence": raw_confidence,
        "domain": domain,
    }


def resolve_files(args: argparse.Namespace) -> list[str]:
    explicit: list[str] | None = resolve_explicit_files(args.files, args.files_from)
    if explicit is not None:
        return explicit
    base_ref = args.base_ref or os.environ.get("BASE_REF") or DEFAULT_BASE_REF
    files: list[str] = changed_files_from_git(base_ref)
    return files


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Compose merge-gate ChangeContext JSON.")
    ap.add_argument("--mech-pass", dest="mech_pass", action="store_true")
    ap.add_argument("--no-mech-pass", dest="mech_pass", action="store_false")
    ap.set_defaults(mech_pass=False)  # fail-safe: unknown mechanical state is a failure
    source = ap.add_mutually_exclusive_group()
    source.add_argument("--files", nargs="+", help="explicit changed-file list")
    source.add_argument("--files-from", help="NUL-delimited changed-file list (git diff --name-only -z)")
    ap.add_argument("--base-ref", help=f"diff base (default $BASE_REF or {DEFAULT_BASE_REF})")
    ap.add_argument("--mapping", default=DEFAULT_MAPPING_PATH)
    kind = ap.add_mutually_exclusive_group()
    kind.add_argument(
        "--human",
        action="store_true",
        help="seed path: reserved human/<domain> namespace, confidence forced to 0.0",
    )
    kind.add_argument("--confidence", type=float, help="agent-reported confidence in [0, 1]")
    ap.add_argument("--output", help="write JSON here instead of stdout")
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging()
    try:
        mapping = DomainMapping.load(args.mapping)
        files = resolve_files(args)
        context = build_context(
            files,
            mapping,
            mech_pass=args.mech_pass,
            human=args.human,
            confidence=args.confidence,
        )
    except ConfigError as exc:
        logger.error("merge-gate-context: %s", exc)
        return EXIT_CONFIG
    payload = json.dumps(context, sort_keys=True)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(payload + "\n")
    else:
        print(payload)
    logger.info(
        "merge-gate-context: domain=%s touches_protected=%s mech_pass=%s files=%d",
        context["domain"],
        context["touches_protected"],
        context["mech_pass"],
        len(files),
    )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
