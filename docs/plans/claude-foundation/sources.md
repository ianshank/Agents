# Pinned Sources — `claude-foundation` Plan & Review

All official Claude Code documentation claims in [REVIEW.md](REVIEW.md) and [PLAN.md](PLAN.md) were verified against these pages on **2026-07-02**. This file seeds §6.1 step 2 of the plan (the new repo's own `/docs/sources.md` should re-pin at scaffold time and record the snapshot date).

## Install / CLI (Review F1)

- https://code.claude.com/docs/en/discover-plugins.md — `/plugin install <plugin>@<marketplace>`; `claude plugin install [--scope user|project|local]`; `claude plugin marketplace add`; enable/disable/uninstall. **No `claude plugin add --path` command exists.** Local session-scoped loading: `claude --plugin-dir <path>`.
- https://code.claude.com/docs/en/plugins-reference.md — `claude plugin validate` (official manifest/structure checker, "Debugging and development tools" section).

## Plugin layout & environment variables (Review m3, confirmed claims)

- https://code.claude.com/docs/en/plugins-reference.md — `.claude-plugin/plugin.json` (manifest only in that directory); `skills/`, `agents/`, `hooks/hooks.json`, `.mcp.json`, `.lsp.json` at plugin **root**; `${CLAUDE_PLUGIN_ROOT}`, `${CLAUDE_PLUGIN_DATA}`, `${CLAUDE_PROJECT_DIR}`.
- https://code.claude.com/docs/en/plugins.md — structure overview; namespacing (`plugin-name:skill-name`; nested agent dirs → `plugin:dir:name`).

## Schemas (Review F3)

- https://code.claude.com/docs/en/plugins-reference.md — field reference is the authoritative spec; **no official JSON Schemas are published** for plugin.json/marketplace.json; `$schema` field tolerated for editors, ignored at load time.

## Marketplace & version pinning (Review F6, confirmed claims)

- https://code.claude.com/docs/en/plugin-marketplaces.md — marketplace entry `source` supports git `ref` (branch/tag) and `sha` pinning; release channels; advanced entries with inline hooks/mcpServers using `${CLAUDE_PLUGIN_ROOT}`.
- https://code.claude.com/docs/en/plugins-reference.md — version management: explicit semver `version` in plugin.json vs commit-SHA versioning.
- https://code.claude.com/docs/en/plugin-dependencies.md — npm-style semver ranges (`~`, `^`, `>=`) for plugin dependencies.

## Skills & evals (Review F2, m2)

- https://code.claude.com/docs/en/skills.md — SKILL.md frontmatter reference (`name`, `description`, `when_to_use`, `disable-model-invocation`, `allowed-tools`, `model`, `effort`, `context: fork`, `agent`, `hooks`); **combined `description` + `when_to_use` cap: 1,536 characters**; "Run evals with skill-creator" — `evals/evals.json`, isolated subagent per case, `grading.json`, benchmark/A-B/trigger-tuning.
- https://agentskills.io/skill-creation/evaluating-skills — open-standard eval file format used by skill-creator.
- Official plugin: `/plugin install skill-creator@claude-plugins-official`.

## Subagents (Review F7, m1)

- https://code.claude.com/docs/en/sub-agents.md — frontmatter fields (`name`, `description`, `model`, `tools`, `disallowedTools`, `effort`, `maxTurns`, `skills`, `permissionMode`, `memory`, `hooks`, `mcpServers`, `isolation`); valid `model` values: aliases (`haiku`/`sonnet`/`opus`), full IDs, `inherit`; **plugin-shipped agents ignore `hooks`, `mcpServers`, `permissionMode`** (security restriction).

## Hooks (Review m4, confirmed claims)

- https://code.claude.com/docs/en/hooks-guide.md and https://code.claude.com/docs/en/hooks.md — lifecycle event list (PreToolUse, PostToolUse, SessionStart/End, UserPromptSubmit, Stop, SubagentStart/Stop, PreCompact/PostCompact, etc.); exit-code semantics (0 = no decision/parse stdout JSON; 2 = block, stderr fed to Claude; other = non-blocking error); JSON control via `hookSpecificOutput.permissionDecision` (`allow`/`deny`/`ask`/`defer`) and `additionalContext`.

## Repository evidence (`ianshank/Agents`, Review F4)

Verified in-repo on 2026-07-02:

- `skills/marketplace.yaml`, `skills/marketplace.schema.json`, `scripts/skill_marketplace.py` — existing custom (non-Claude-native) skill marketplace.
- `scripts/validate_skill.py` + per-skill vendored copies + `scripts/check_skill_script_drift.py` — vendored-copy-with-drift-guard pattern; `docs/decisions/` ADR 0009.
- `.github/workflows/skills-ci.yml` — per-skill CI matrix (Python 3.10–3.12), ≥95% branch coverage, tiered skill validation.
- Absent: `.claude/` directory, `.claude-plugin/`, `.mcp.json`, subagent definitions, hook scripts, `CLAUDE.md`; no references to `MouseDroid-AGI`, `piodeer`, `SQE`, or `claude-foundation` anywhere in the repo.
