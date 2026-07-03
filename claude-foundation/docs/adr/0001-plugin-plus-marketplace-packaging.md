# 0001 — Package as a Claude Code plugin with a self-hosted marketplace, not a copy-template

- Status: **Accepted.**
- Date: 2026-07-03
- Related: `docs/plans/claude-foundation/PLAN.md` in `ianshank/Agents` (§1.3, §2.1, Usage Note 2);
  Agents ADR 0017 (claude-foundation reconciliation: plugin supplies the generic layer,
  consumer's custom machinery stays).

## Context

Reusable Claude Code components (skills, subagents, hooks, MCP config) are needed across
several repositories (Agents, MouseDroid-AGI, piodeer, SQE platform). The obvious
alternatives are a template repository that consumers copy from, or vendoring files into
each consumer. Both reproduce the drift failure mode this repository exists to prevent —
the Agents repo already needed a vendored-copy drift guard (its ADR 0009) to manage
exactly that pattern intra-repo. Claude Code provides a native distribution mechanism:
plugins discovered through marketplaces, with git `ref`/`sha` pinning on marketplace
source entries.

## Decision

1. **Package everything as a single Claude Code plugin** named `foundation`
   (`.claude-plugin/plugin.json`), with components at the plugin root (`skills/`,
   `agents/`, `hooks/`, `.mcp.json.example`). The plugin name — not the repository
   name — owns the `foundation:*` component namespace.
2. **Distribute via a self-hosted marketplace in the same repository**
   (`.claude-plugin/marketplace.json`). Consumers run
   `claude plugin marketplace add <repo>` then
   `claude plugin install foundation@claude-foundation`.
3. **Consumers pin semver tags** via the marketplace entry's `ref` (or `sha`) field.
   Upgrades are deliberate, reviewable configuration diffs — never silent.
4. **Component names are append-only within a major version.** Renaming or removing a
   released skill, subagent, or hook requires a major version bump. A release-gate
   manifest diff enforces this against the previous minor's public surface.
5. **Consumers install, never vendor.** Per Agents ADR 0017, integration is
   configuration-only: a marketplace entry plus install scope. Copying plugin files into
   a consumer repo is the prohibited drift path.

## Consequences

- One source of truth: a fix to a skill or hook ships to every consumer as a version
  bump, not N copy-paste patches.
- The repository must maintain a real compatibility contract (semver discipline,
  append-only names, backwards-compat fixture in the release gate) — cheap for a
  template, mandatory for a dependency.
- Consumers with pre-existing component systems (e.g. Agents' custom skill
  marketplace) coexist by namespace separation: this plugin owns `foundation:*` and
  supplies only the generic layer; domain machinery stays in the consumer (ADR 0017).
- Publishing to third-party marketplaces stays out of scope; the self-hosted
  marketplace is sufficient for the intended consumers.
