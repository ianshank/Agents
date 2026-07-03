from __future__ import annotations

import pytest
from pydantic import ValidationError

from foundation_tools import schemas


def test_plugin_manifest_valid_and_name_rules() -> None:
    manifest = schemas.PluginManifest.model_validate({"name": "foundation", "version": "1.0.0"})
    assert manifest.name == "foundation"
    with pytest.raises(ValidationError, match="kebab-case"):
        schemas.PluginManifest.model_validate({"name": "Not_Kebab", "version": "1.0.0"})
    with pytest.raises(ValidationError, match="semver"):
        schemas.PluginManifest.model_validate({"name": "ok", "version": "v1"})


def test_marketplace_requires_plugins() -> None:
    with pytest.raises(ValidationError, match="at least one plugin"):
        schemas.MarketplaceManifest.model_validate(
            {"name": "m", "owner": {"name": "o"}, "plugins": []}
        )


def test_skill_frontmatter_description_budget() -> None:
    ok = schemas.SkillFrontmatter.model_validate({"name": "s", "description": "d" * 100})
    assert ok.name == "s"
    with pytest.raises(ValidationError, match="budget"):
        schemas.SkillFrontmatter.model_validate(
            {
                "name": "s",
                "description": "d" * 1000,
                "when_to_use": "w" * (schemas.SKILL_DESCRIPTION_BUDGET - 999),
            }
        )


def test_skill_frontmatter_allows_documented_optional_fields() -> None:
    # model/effort/hooks are documented SKILL.md fields; accept them...
    fm = schemas.SkillFrontmatter.model_validate(
        {"name": "s", "description": "d", "model": "haiku", "effort": "high", "hooks": {"x": []}}
    )
    assert fm.model == "haiku" and fm.effort == "high"


def test_skill_frontmatter_model_is_alias_only() -> None:
    # ...but a skill still cannot pin a full model ID (same policy as agents).
    with pytest.raises(ValidationError, match="full model IDs are banned"):
        schemas.SkillFrontmatter.model_validate(
            {"name": "s", "description": "d", "model": "claude-" + "opus-4-8"}
        )


def test_skill_frontmatter_rejects_unknown_fields_and_bad_context() -> None:
    with pytest.raises(ValidationError):
        schemas.SkillFrontmatter.model_validate(
            {"name": "s", "description": "d", "totally_unknown": 1}
        )
    with pytest.raises(ValidationError, match="fork"):
        schemas.SkillFrontmatter.model_validate(
            {"name": "s", "description": "d", "context": "thread"}
        )
    fork = schemas.SkillFrontmatter.model_validate(
        {"name": "s", "description": "d", "context": "fork", "allowed-tools": "Read, Grep"}
    )
    assert fork.allowed_tools == "Read, Grep"


def test_agent_frontmatter_model_alias_policy() -> None:
    for alias in sorted(schemas.ALLOWED_MODEL_VALUES):
        agent = schemas.AgentFrontmatter.model_validate(
            {"name": "a", "description": "d", "model": alias}
        )
        assert agent.model == alias
    with pytest.raises(ValidationError, match="full model IDs are banned"):
        schemas.AgentFrontmatter.model_validate(
            {"name": "a", "description": "d", "model": "claude-" + "opus-4-8"}
        )


@pytest.mark.parametrize("field", sorted(schemas.PLUGIN_AGENT_FORBIDDEN_FIELDS))
def test_agent_frontmatter_rejects_plugin_ignored_fields(field: str) -> None:
    with pytest.raises(ValidationError):
        schemas.AgentFrontmatter.model_validate({"name": "a", "description": "d", field: {}})


def test_eval_suite_requires_three_cases_with_assertions() -> None:
    case = {"id": "c", "prompt": "p", "expected_behavior": "e", "assertions": ["a"]}
    suite = schemas.EvalSuite.model_validate({"skill": "s", "cases": [case, case, case]})
    assert len(suite.cases) == 3
    with pytest.raises(ValidationError):
        schemas.EvalSuite.model_validate({"skill": "s", "cases": [case]})
    with pytest.raises(ValidationError):
        schemas.EvalSuite.model_validate({"skill": "s", "cases": [dict(case, assertions=[])] * 3})


def test_grading_report_tolerates_extra_fields() -> None:
    report = schemas.GradingReport.model_validate(
        {
            "skill": "s",
            "runner": "skill-creator",
            "cases": [{"id": "c", "passed": True, "latency_ms": 12}],
        }
    )
    assert report.cases[0].passed is True
