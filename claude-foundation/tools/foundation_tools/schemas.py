"""Pinned, doc-derived schemas for plugin components.

No official JSON Schemas are published for Claude Code plugin manifests; these
models are hand-derived from the official docs (see docs/sources.md for the
pinned references and derivation date) and enforced alongside the official
``claude plugin validate`` checker, which remains authoritative.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Combined description + when_to_use budget for a skill's listing entry.
SKILL_DESCRIPTION_BUDGET = 1536

# Model aliases permitted in frontmatter; full model IDs are banned everywhere
# (scanner policy) so selection stays config-level and portable. Kept in sync
# with docs/sources.md (sub-agents frontmatter reference).
ALLOWED_MODEL_VALUES = frozenset({"haiku", "sonnet", "opus", "fable", "inherit"})

# Plugin-shipped agents ignore these for security; shipping them is a defect.
PLUGIN_AGENT_FORBIDDEN_FIELDS = frozenset({"hooks", "mcpServers", "permissionMode"})

_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")


def validate_model_alias(value: str | None) -> str | None:
    """Reject full model IDs; permit the documented aliases and ``inherit``.

    Shared by skill and agent frontmatter so the no-hardcoded-model-ID policy
    is enforced identically wherever ``model:`` may appear.
    """
    if value is not None and value not in ALLOWED_MODEL_VALUES:
        raise ValueError(
            f"model must be one of {sorted(ALLOWED_MODEL_VALUES)}; "
            "full model IDs are banned (portability)"
        )
    return value


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PluginAuthor(_StrictModel):
    name: str
    email: str | None = None
    url: str | None = None


class PluginManifest(_StrictModel):
    """``.claude-plugin/plugin.json``."""

    name: str
    version: str
    description: str | None = None
    author: PluginAuthor | None = None
    homepage: str | None = None
    repository: str | None = None
    license: str | None = None
    keywords: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _name_shape(cls, value: str) -> str:
        if not _NAME_RE.match(value):
            raise ValueError("plugin name must be kebab-case (it sets the component namespace)")
        return value

    @field_validator("version")
    @classmethod
    def _semver(cls, value: str) -> str:
        if not re.match(r"^\d+\.\d+\.\d+(?:[-+].+)?$", value):
            raise ValueError("version must be semver MAJOR.MINOR.PATCH")
        return value


class MarketplacePluginEntry(_StrictModel):
    name: str
    source: str | dict[str, Any]
    description: str | None = None
    version: str | None = None


class MarketplaceOwner(_StrictModel):
    name: str
    email: str | None = None
    url: str | None = None


class MarketplaceManifest(_StrictModel):
    """``.claude-plugin/marketplace.json``."""

    name: str
    owner: MarketplaceOwner
    metadata: dict[str, Any] | None = None
    plugins: list[MarketplacePluginEntry]

    @model_validator(mode="after")
    def _has_plugins(self) -> MarketplaceManifest:
        if not self.plugins:
            raise ValueError("marketplace must list at least one plugin")
        return self


class SkillFrontmatter(_StrictModel):
    """``skills/<name>/SKILL.md`` frontmatter (doc-derived optional fields).

    All optional SKILL.md fields the docs define are accepted; ``model`` is held
    to the same alias-only policy as agents so a skill cannot pin a model ID.
    """

    name: str
    description: str
    when_to_use: str | None = None
    allowed_tools: str | None = Field(default=None, alias="allowed-tools")
    context: str | None = None
    agent: str | None = None
    model: str | None = None
    effort: str | None = None
    hooks: dict[str, Any] | None = None
    disable_model_invocation: bool | None = Field(default=None, alias="disable-model-invocation")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @model_validator(mode="after")
    def _description_budget(self) -> SkillFrontmatter:
        combined = len(self.description) + len(self.when_to_use or "")
        if combined > SKILL_DESCRIPTION_BUDGET:
            raise ValueError(
                f"description + when_to_use is {combined} chars; "
                f"budget is {SKILL_DESCRIPTION_BUDGET}"
            )
        return self

    @field_validator("model")
    @classmethod
    def _model_alias_only(cls, value: str | None) -> str | None:
        return validate_model_alias(value)

    @field_validator("context")
    @classmethod
    def _context_value(cls, value: str | None) -> str | None:
        if value is not None and value != "fork":
            raise ValueError("context must be 'fork' when set")
        return value


class AgentFrontmatter(_StrictModel):
    """``agents/<name>.md`` frontmatter, restricted to plugin-honored fields."""

    name: str
    description: str
    tools: str | None = None
    model: str | None = None
    effort: str | None = None
    max_turns: int | None = Field(default=None, alias="maxTurns")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @field_validator("name")
    @classmethod
    def _name_shape(cls, value: str) -> str:
        if not _NAME_RE.match(value):
            raise ValueError("agent name must be kebab-case")
        return value

    @field_validator("model")
    @classmethod
    def _model_alias_only(cls, value: str | None) -> str | None:
        return validate_model_alias(value)


class EvalCase(_StrictModel):
    id: str
    prompt: str
    expected_behavior: str
    assertions: list[str] = Field(min_length=1)


class EvalSuite(_StrictModel):
    """``skills/<name>/evals/evals.json`` (skill-creator / agentskills.io format)."""

    skill: str
    version: int = 1
    cases: list[EvalCase] = Field(min_length=3)


class GradingCase(_StrictModel):
    id: str
    passed: bool
    evidence: str | None = None

    model_config = ConfigDict(extra="allow")


class GradingReport(_StrictModel):
    """``grading.json`` produced by an eval run; consumed by the release gate."""

    skill: str
    cases: list[GradingCase]

    model_config = ConfigDict(extra="allow")
