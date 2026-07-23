"""Reserved merge-gate domain namespaces (ADR 0018 §5, ADR 0023).

The single, CANONICAL Python source of the reserved *human* namespace, so ``agent_core``
code and the ``scripts`` that depend on it stop re-spelling the ``"human/"`` literal.
``agent_core`` stays deliberately config-free (it never reads
``config/merge-gate-domains.yaml``). The YAML ``human_namespace`` is a *mirror* of this
constant for operator visibility, NOT an independent override: ``is_agent_domain`` below
classifies against this literal, so a YAML value that differed would seed rows under one
prefix while classification used another — the exact agent-pool-poisoning hazard
(REVIEW.md §6). ``merge_gate_context.DomainMapping.load`` validates the YAML equals this
constant at load (fail-loud), and F-045 pins the two statically as a second line.
"""

from __future__ import annotations

# The reserved namespace prefix human-authored merges seed under. Agent-calibration
# domains are, by definition, every domain that does NOT carry it.
HUMAN_NAMESPACE = "human/"


def is_agent_domain(domain: str) -> bool:
    """True for agent-calibration domains (everything outside the reserved human namespace)."""
    return not domain.startswith(HUMAN_NAMESPACE)


def strip_human_namespace(domain: str) -> str:
    """Return the bare domain, dropping a leading reserved human namespace if present."""
    return domain[len(HUMAN_NAMESPACE) :] if domain.startswith(HUMAN_NAMESPACE) else domain
