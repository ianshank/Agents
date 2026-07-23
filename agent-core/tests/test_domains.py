"""Tests for agent_core.domains — the single-sourced reserved namespace (ADR 0023)."""

from __future__ import annotations

from agent_core.domains import HUMAN_NAMESPACE, is_agent_domain, strip_human_namespace


def test_human_namespace_constant():
    assert HUMAN_NAMESPACE == "human/"


def test_is_agent_domain():
    assert is_agent_domain("agent-core") is True
    assert is_agent_domain("eval-harness") is True
    assert is_agent_domain("human/agent-core") is False
    assert is_agent_domain("human/") is False


def test_strip_human_namespace():
    assert strip_human_namespace("human/agent-core") == "agent-core"
    assert strip_human_namespace("human/docs") == "docs"
    assert strip_human_namespace("agent-core") == "agent-core"  # already bare
    assert strip_human_namespace("humanish/x") == "humanish/x"  # not the reserved prefix
