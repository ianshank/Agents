#!/usr/bin/env python3
"""Validation script for F-045 — agent-seeding hardening & reuse (F-042..F-044 follow-up).

Deterministic and offline: reads workflow / config / module TEXT only (no agent_core import,
which the validation gate does not install). Pins the durable hardening invariants so a
future edit cannot silently regress them.

    1. The seed workflow's classifier call is FAIL-SAFE — a non-zero exit routes the merge to
       the human lane instead of aborting the whole seed job (ADR 0023 §2).
    2. github.actor is routed through env in both push steps, never spliced into a run: script
       (zizmor template-injection anti-pattern).
    3. The reserved human namespace has ONE Python source (agent_core.domains.HUMAN_NAMESPACE)
       that agrees with config/merge-gate-domains.yaml's human_namespace.
    4. The one-off migration is no longer excluded from the scripts coverage gate.
    5. The shared scripts/_config.py exists and agent_confidence + merge_gate_context reuse it
       (the duplicated changed-file / YAML-loader idioms were removed).

Exit codes: 0 all checks passed; 1 one or more failed.
"""

from __future__ import annotations

import logging
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.dirname(_HERE)
for _p in (_HERE, _SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import yaml
from _common import check as _check
from _common import configure_logging, report

logger = logging.getLogger(__name__)

_ROOT = os.path.dirname(_SCRIPTS)


def _read(rel_path: str) -> str:
    with open(os.path.join(_ROOT, rel_path), encoding="utf-8") as fh:
        return fh.read()


def validate_f045() -> int:
    configure_logging()
    errors: list[str] = []

    seed = _read(os.path.join(".github", "workflows", "merge-gate-seed.yml"))
    labeller = _read(os.path.join(".github", "workflows", "outcome-labeller.yml"))

    # 1. fail-safe classifier routing
    _check(
        "if ! python scripts/agent_confidence.py" in seed,
        "seed workflow routes to the human lane on a classifier failure (fail-safe)",
        errors,
    )

    # 2. github.actor via env, never spliced into a run: script
    for name, wf in (("merge-gate-seed", seed), ("outcome-labeller", labeller)):
        _check("GH_ACTOR" in wf, f"{name}: actor routed through env (GH_ACTOR)", errors)
        _check(
            '--actor "${{ github.actor }}"' not in wf,
            f"{name}: github.actor is not spliced into the run script",
            errors,
        )

    # 3. HUMAN_NAMESPACE single-sourced in agent_core and agreeing with the operator YAML
    mapping = yaml.safe_load(_read(os.path.join("config", "merge-gate-domains.yaml")))
    yaml_ns = str(mapping.get("human_namespace", ""))
    domains_src = _read(os.path.join("agent-core", "agent_core", "domains.py"))
    match = re.search(r'HUMAN_NAMESPACE\s*=\s*"([^"]+)"', domains_src)
    py_ns = match.group(1) if match else ""
    _check(
        bool(py_ns) and py_ns == yaml_ns,
        f"HUMAN_NAMESPACE single-sourced and agrees with config ({py_ns!r} == {yaml_ns!r})",
        errors,
    )

    # 4. migration measured by the scripts coverage gate (no longer omitted)
    _check(
        "scripts/migrations" not in _read(os.path.join("scripts", ".coveragerc")),
        "migration is not excluded from the scripts coverage gate",
        errors,
    )

    # 5. shared _config.py exists and is reused (DRY)
    _check(os.path.exists(os.path.join(_ROOT, "scripts", "_config.py")), "shared scripts/_config.py exists", errors)
    for mod in ("agent_confidence.py", "merge_gate_context.py"):
        _check(
            "from _config import" in _read(os.path.join("scripts", mod)),
            f"{mod} reuses the shared _config helpers",
            errors,
        )

    return report(logger, "F-045", errors)


def main() -> int:
    return validate_f045()


if __name__ == "__main__":
    sys.exit(main())
