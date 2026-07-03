# Pinned Sources — claude-foundation provenance record

This repository's schemas (`foundation_tools/schemas.py`), validator rules, and CLI/hook
contracts are hand-derived from the official Claude Code documentation — no official
JSON Schemas are published. This file records the doc snapshot they were derived from.

Originally pinned **2026-07-02** during plan review (`ianshank/Agents`,
`docs/plans/claude-foundation/sources.md`); **re-pinned 2026-07-03** at scaffold time.
Any schema or contract change must re-verify against these pages and update this date.

## Install / CLI

- https://code.claude.com/docs/en/discover-plugins.md — `/plugin install <plugin>@<marketplace>`; `claude plugin install [--scope user|project|local]`; `claude plugin marketplace add`; enable/disable/uninstall. **No `claude plugin add --path` command exists.** Local session-scoped loading: `claude --plugin-dir <path>`.
- https://code.claude.com/docs/en/plugins-reference.md — `claude plugin validate` (official manifest/structure checker, "Debugging and development tools" section).

## Plugin layout & environment variables

- https://code.claude.com/docs/en/plugins-reference.md — `.claude-plugin/plugin.json` (manifest only in that directory); `skills/`, `agents/`, `hooks/hooks.json`, `.mcp.json`, `.lsp.json` at plugin **root**; `${CLAUDE_PLUGIN_ROOT}`, `${CLAUDE_PLUGIN_DATA}`, `${CLAUDE_PROJECT_DIR}`.
- https://code.claude.com/docs/en/plugins.md — structure overview; namespacing (`plugin-name:skill-name`; nested agent dirs → `plugin:dir:name`).

## Schemas

- https://code.claude.com/docs/en/plugins-reference.md — field reference is the authoritative spec; **no official JSON Schemas are published** for plugin.json/marketplace.json; `$schema` field tolerated for editors, ignored at load time. The pinned models in `foundation_tools/schemas.py` are derived from this page.

## Marketplace & version pinning

- https://code.claude.com/docs/en/plugin-marketplaces.md — marketplace entry `source` supports git `ref` (branch/tag) and `sha` pinning; release channels; advanced entries with inline hooks/mcpServers using `${CLAUDE_PLUGIN_ROOT}`.
- https://code.claude.com/docs/en/plugins-reference.md — version management: explicit semver `version` in plugin.json vs commit-SHA versioning.
- https://code.claude.com/docs/en/plugin-dependencies.md — npm-style semver ranges (`~`, `^`, `>=`) for plugin dependencies.

## Skills & evals

- https://code.claude.com/docs/en/skills.md — SKILL.md frontmatter reference (`name`, `description`, `when_to_use`, `disable-model-invocation`, `allowed-tools`, `model`, `effort`, `context: fork`, `agent`, `hooks`); **combined `description` + `when_to_use` cap: 1,536 characters**; "Run evals with skill-creator" — `evals/evals.json`, isolated subagent per case, `grading.json`, benchmark/A-B/trigger-tuning.
- https://agentskills.io/skill-creation/evaluating-skills — open-standard eval file format used by skill-creator (the format shipped in each skill's `evals/evals.json`).
- Official plugin: `/plugin install skill-creator@claude-plugins-official` (wrapped by `foundation_tools.eval_gate`).

## Subagents

- https://code.claude.com/docs/en/sub-agents.md — frontmatter fields (`name`, `description`, `model`, `tools`, `disallowedTools`, `effort`, `maxTurns`, `skills`, `permissionMode`, `memory`, `hooks`, `mcpServers`, `isolation`); valid `model` values: aliases (`haiku`/`sonnet`/`opus`), full IDs, `inherit`; **plugin-shipped agents ignore `hooks`, `mcpServers`, `permissionMode`** (security restriction — enforced by the validator).

## Hooks

- https://code.claude.com/docs/en/hooks-guide.md and https://code.claude.com/docs/en/hooks.md — lifecycle event list (PreToolUse, PostToolUse, SessionStart/End, UserPromptSubmit, Stop, SubagentStart/Stop, PreCompact/PostCompact, etc.); exit-code semantics (0 = no decision/parse stdout JSON; 2 = block, stderr fed to Claude; other = non-blocking error); JSON control via `hookSpecificOutput.permissionDecision` (`allow`/`deny`/`ask`/`defer`) and `additionalContext`. These are the mechanics behind ADR 0002.
