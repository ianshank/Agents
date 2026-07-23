"""Reserved merge-gate domain namespaces (ADR 0018 §5, ADR 0023).

Single Python source of the reserved *human* namespace, so ``agent_core`` code and the
``scripts`` that depend on it stop re-spelling the ``"human/"`` literal. ``agent_core``
stays deliberately config-free (it never reads ``config/merge-gate-domains.yaml``); the
YAML ``human_namespace`` remains the operator-facing override that ``merge_gate_context``
loads, and F-045 asserts the two agree so they cannot drift.
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
