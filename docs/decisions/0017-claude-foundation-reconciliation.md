# 0017 — claude-foundation reconciliation: plugin for the generic layer, custom marketplace stays

- Status: **Accepted.** Prerequisite for `claude-foundation` M7 (dogfood into this repo);
  decision only — no code changes here until the plugin's v1.0.0 exists.
- Date: 2026-07-03
- Related: `docs/plans/claude-foundation/PLAN.md` (§6.2 M7), `docs/plans/claude-foundation/REVIEW.md`
  (finding F4), ADR 0009 (vendored-copy drift guard), F-023 (skill marketplace), F-031
  (operational-scripts quality gates).

## Context

The planned `claude-foundation` repository packages reusable Claude Code components —
generic skills (`foundation:plan`, `foundation:code-review`, `foundation:test-first`,
`foundation:c4-docs`), least-privilege subagents (`explorer`, `test-runner`), and lifecycle
hook guards — as a Claude Code plugin with a self-hosted marketplace, and names this repo
as its first consumer.

This repo, however, already has a mature, CI-enforced **custom** skill system that predates
the plugin: four domain skills (`openai-judge`, `architecture-drift-guard`,
`eval-corpus-forge`, `model-bench`) in the v2.0 frontmatter convention
(`validator_version`, `compatibility`, semver `version`), a schema-validated registry
(`skills/marketplace.yaml` + `scripts/skill_marketplace.py`, F-023), per-skill CI with ≥95%
branch-coverage gates (`skills-ci.yml`), and the vendored `validate_skill.py` drift guard
(ADR 0009). The plugin's `.claude-plugin/marketplace.json` format and Anthropic's SKILL.md
convention overlap with none of that machinery, so "install the plugin" is not a clean
no-op: without an explicit decision, two marketplace formats and two skill conventions
would compete in one repo, and the tempting shortcuts (migrate the four skills, or
dual-publish them) each break something that currently works.

## Decision

1. **This repo keeps its four domain skills exactly where and as they are.** They are
   application code — runtime eval tooling with tests, coverage gates, CI jobs, and a
   registry contract — not agent-workflow procedures. No migration to the plugin SKILL.md
   convention, no dual-publishing, no changes to `skills/marketplace.yaml`,
   `skill_marketplace.py`, `validate_skill.py`, `skills-ci.yml`, or the drift guard.
2. **`claude-foundation` supplies only the generic layer.** The plugin's skills, subagents,
   and hook guards are agent-workflow procedures with no runtime coupling to the harness.
   This repo consumes them by **installing** the plugin (marketplace entry pinned to a
   semver `ref`/`sha`), never by vendoring files into the repo — copying is the drift
   failure mode both ADR 0009 and the plugin exist to prevent.
3. **Namespace separation is the coexistence contract.** Plugin components live under the
   `foundation:*` namespace (from the plugin's `name` field); this repo's custom skills are
   invoked through their own scripts/CLI and never claim that namespace. A future generic
   skill goes to `claude-foundation`; a future domain skill (anything importing
   `eval_harness`/`agent_core` or gated by this repo's CI) goes here.
4. **Install surface is config-only.** Dogfooding (M7) touches Claude Code configuration
   (marketplace add + plugin install, scope per developer or project settings) and may add
   a short README/CLAUDE.md note. It adds no Python, no workflow jobs, and nothing under
   `skills/` — so it cannot trip the protected-path guard or require ledger changes beyond
   an optional documentation feature entry.

### Alternatives rejected

- **Migrate the four skills into the plugin format:** loses the ≥95% coverage gates,
  per-skill CI isolation, and registry semver contract for zero behavioural gain; the
  plugin convention has no equivalent of the v2.0 validator tiers.
- **Dual-publish (shim the custom skills into the plugin marketplace too):** reintroduces
  copy-drift between two sources of truth — the exact problem the plugin was proposed to
  solve.
- **Build the plugin inside this repo as a subdirectory:** entangles the plugin's release
  cadence with the harness's, defeats cross-repo reuse (`MouseDroid-AGI`, `piodeer`, SQE),
  and puts generic agent tooling behind this repo's eval-integrity gates where it does not
  belong.

## Consequences

- **Nothing in this repo changes now.** M7 is unblocked once `claude-foundation` tags
  v1.0.0; the integration lands as configuration plus docs, reviewable in isolation.
- **Clear routing rule for future skills** (generic → foundation, domain → here) prevents
  the ambiguity from recurring; the rule is recorded in NEXT_STEPS and PLAN.md M7.
- **The custom marketplace remains authoritative for domain skills.** Any future decision
  to converge formats would be a new ADR superseding this one, presumably after the plugin
  ecosystem gains equivalents of the coverage/validator machinery it lacks today.
- **Version pinning discipline carries over:** the consumer marketplace entry pins a tag;
  upgrades are deliberate, reviewable diffs (PLAN.md §1.2 backwards-compat criteria apply on
  the plugin side).
