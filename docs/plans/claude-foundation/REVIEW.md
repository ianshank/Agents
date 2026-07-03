# Peer Review: `claude-foundation` Plugin Repository Plan

**Reviewed artifact:** "Plan: `claude-foundation` — Reusable Claude Code Plugin Repository" (constraint-programming template instantiation, v as submitted 2026-07-02).
**Review basis:** (a) current official Claude Code documentation (see [sources.md](sources.md) for pinned URLs), (b) the actual contents of the `ianshank/Agents` repository, which the plan names as its first consumer (§6.2 M7).
**Revised plan incorporating all fixes:** [PLAN.md](PLAN.md).

---

## Overall verdict

**Strong plan — B+.** The constraint-programming structure delivers real value: the success criteria are mechanically verifiable, invariants are explicit (append-only component names within a major version, fail-open/fail-closed hook policy), the milestone order builds a walking skeleton before components, and the Usage Note honestly documents deviations from its source template. The distribution model (plugin + self-hosted marketplace, consumers pin semver tags) is the correct native mechanism — marketplace entries support `ref`/`sha` pinning exactly as the plan assumes.

However, the plan contains **two factual errors about the Claude Code CLI/schema surface**, **one major duplication-of-effort item**, and **a premise that does not survive contact with its own first consumer**. All are fixable without changing the plan's architecture. Findings below are ordered by severity; each carries its evidence.

---

## Blocking findings (must fix before execution)

### F1. The headline success criterion uses a nonexistent CLI command

§1.2 (first criterion) and §4.1 command 8 depend on `claude plugin add --path .`. **This command does not exist.** The real, scriptable mechanisms are:

- **Local/CI testing:** `claude --plugin-dir ./path/to/plugin` — loads the plugin for the session without installing it.
- **Real install:** `claude plugin marketplace add <repo-or-path>` followed by `claude plugin install <plugin>@<marketplace> [--scope user|project|local]`.
- **Manifest validation:** `claude plugin validate` — an official checker the plan doesn't use at all; it should be verification command #0.

**Fix:** rewrite the smoke test as (1) `claude plugin validate .`, (2) `claude plugin marketplace add` + `claude plugin install` into a temp consumer repo, (3) headless invocation of one namespaced skill.
**Evidence:** plugins-reference and discover-plugins docs (sources.md §Install/CLI).

### F2. Milestone M5 (custom EvalRunner) largely rebuilds official tooling

The official `skill-creator` plugin (`/plugin install skill-creator@claude-plugins-official`) already provides **exactly the convention the plan proposes to build**: per-skill `evals/evals.json` test cases, isolated subagent execution per case, `grading.json` with pass/fail evidence — plus benchmarking (with-skill vs. without-skill), blind A/B comparison between skill versions, and description trigger-rate tuning that the plan doesn't even ask for. The eval file format is an open standard (agentskills.io), not a private convention.

The custom Pydantic/Protocol-DI `EvalRunner` (§C4 Level 3–4, M5) is the plan's single largest engineering item, and it duplicates a maintained official tool.

**Fix:** adopt the skill-creator format and runner; build only a **thin CI wrapper** (headless invocation + gate on `grading.json` results). M5 collapses from "build an eval framework" to "integrate one." Retain the Protocol-DI design only if skill-creator proves non-scriptable in CI — record the outcome as an ADR either way.
**Evidence:** skills doc, "Run evals with skill-creator" (sources.md §Skills/Evals).

### F3. No official JSON Schemas exist for `plugin.json` / `marketplace.json`

§1.2 requires manifests to "validate against pinned JSON Schemas" as if such schemas are published. They are not: the docs' field reference is the authoritative spec, and `claude plugin validate` is the official checker. (A `$schema` field pointing at json.schemastore.org is tolerated for editor autocomplete but ignored at load time.) The plan's own anti-constraint §2.3 ("generate JSON Schemas by introspection from official docs") quietly acknowledges this, but the success criterion reads as if it were referencing published artifacts.

**Fix:** the criterion becomes "passes `claude plugin validate` **and** passes our hand-derived pinned schemas, documented as *derived from docs on date X*, with the doc snapshot recorded in `/docs/sources.md`."
**Evidence:** plugins-reference §Complete schema, §Debugging tools (sources.md §Schemas).

### F4. The premise is unverifiable, and the first consumer already has competing machinery

§1.3 ¶1 claims "agent/skill/command definitions are currently duplicated and drifting across multiple repos." In the `Agents` repo there is **zero evidence of this**: no `.claude/` directory, no subagents, no hooks, no `.mcp.json`, and no references to MouseDroid-AGI, piodeer, or SQE anywhere (verified by search). The duplication claim may be true across the other repos, but it is not verifiable from the named first consumer.

More importantly, `Agents` (package name: `langfuse-eval-harness`) already has a **mature, CI-enforced custom skill system** that the plan never mentions:

- 4 skills under `skills/` with their own frontmatter convention (`validator_version: '2.0'`, `compatibility`, `version`) — close to, but not, the Claude plugin skill format;
- a custom marketplace: `skills/marketplace.yaml` + `skills/marketplace.schema.json` + `scripts/skill_marketplace.py`;
- a vendored-copy-plus-drift-guard pattern (`scripts/validate_skill.py` copied into each skill, kept in sync by `scripts/check_skill_script_drift.py`, documented in ADR 0009 under `docs/decisions/`) — which is, notably, **prior art for the exact drift problem this plan exists to solve**;
- per-skill CI (`.github/workflows/skills-ci.yml`) with ≥95% branch-coverage gates.

So M7 ("dogfood: install into ianshank/Agents") is not a clean install — it is a **format-collision and reconciliation question**: two marketplace formats (custom YAML vs. `.claude-plugin/marketplace.json`) and two skill frontmatter conventions would coexist and compete.

**Fix:** (1) soften the premise from "consolidating existing duplication" to "establishing a single source of truth before duplication spreads"; (2) add an explicit reconciliation ADR to M7. Recommended resolution, recorded in PLAN.md: keep Agents' four domain skills where they are — they are application code with coverage gates, not generic procedures — and adopt `claude-foundation` in Agents only for the generic layer (plan / code-review / test-first / c4-docs skills, explorer / test-runner subagents, the hook guards).
**Evidence:** `skills/marketplace.yaml`, `scripts/validate_skill.py`, `scripts/check_skill_script_drift.py`, `docs/decisions/` ADR 0009, `.github/workflows/skills-ci.yml` in this repository.

---

## Major findings (should fix)

### F5. Behavioral evals as a merge-blocking CI gate is brittle and expensive

§2.1 requires skill evals "in CI … and required before merge," and §1.2 demands "eval runner reports 100% assertion pass." LLM eval runs are non-deterministic and require API credentials; a 100%-pass-per-PR gate will flake and accumulate cost. The plan's own completion checklist (§6.3) admits "eval runner requires API access" as a known limitation but doesn't draw the conclusion.

**Fix:** split the gates. **Merge-blocking (deterministic):** lint, type-check, shellcheck, schema validation, hardcode scan, hook unit tests, `claude plugin validate`, install smoke. **Release-blocking (behavioral):** evals run on-demand and nightly, and must pass before a version tag is cut — not per PR.

### F6. The backwards-compatibility criterion doesn't test what it says

§1.2: "A consumer repo pinned to v1.x continues to pass its smoke test after a v1.(x+1) release." A consumer pinned via marketplace `ref: v1.x` (or `sha`) is untouched by new releases **by construction** — the criterion is vacuously true. The real risk is consumers on a floating ref, or consumers upgrading.

**Fix:** reword to: "the compat job installs the *new* candidate version into a consumer fixture written against the *previous* minor's public surface (component names, invocation namespaces, hook contracts) and passes" — i.e., directly test the append-only-names invariant — plus a diff check that no released component name disappeared within a major version.

### F7. The hardcode scanner needs an explicit allowlist policy or it fights the plan's own design

§1.2 requires "CI greps for … literal model IDs outside config files → build fails on match," while §2.2 requires "cheapest adequate model per agent" selected **via frontmatter** — and subagent frontmatter legitimately contains model values. Without a policy, the scanner flags the plan's own components.

**Fix:** spell out the policy: model **aliases** (`haiku`, `sonnet`, `opus`, `inherit`) are permitted in frontmatter `model:` fields only; **full model IDs** (e.g., `claude-*-4-*` patterns) are banned everywhere; any model reference in scripts is banned; paths only via `${CLAUDE_PLUGIN_ROOT}` / `${CLAUDE_PROJECT_DIR}`.

---

## Minor findings

- **m1.** Plugin-shipped subagents **ignore** `hooks`, `mcpServers`, and `permissionMode` frontmatter (a documented security restriction). Constrain the `explorer` / `test-runner` designs to `name` / `description` / `tools` / `model` / `effort` / `maxTurns`.
- **m2.** The "skill description budget" soft constraint has a concrete number: `description` + `when_to_use` combined are capped at **1,536 characters**. Encode it as a validator rule, not a vague preference.
- **m3.** Layout nuance: `.claude-plugin/` should contain only `plugin.json` (and, for a marketplace repo, `marketplace.json`); all component directories (`skills/`, `agents/`, `hooks/`) live at the **plugin root**. The plan's layout is correct — the validator should enforce this so it stays correct.
- **m4.** Hook blocking semantics are concrete: exit code 2 + stderr, or exit 0 + JSON `{"hookSpecificOutput": {"permissionDecision": "deny", ...}}`. The fail-open/fail-closed invariant (§1.3 ¶3) should name these mechanisms in the hook specs and their tests.
- **m5.** Python floor: the plan says 3.11+; the first consumer's CI matrix is 3.10–3.12. Fine for an independent repo — note it if any tooling is ever vendored into consumers.
- **m6.** §3.3's "max 25 files modified per pass" will be violated immediately by M0 scaffolding. Raise the cap for scaffolding milestones or scope it to post-skeleton passes.

## Confirmed-correct claims (no change needed)

- `${CLAUDE_PLUGIN_ROOT}` exists and is usable in hook commands, `.mcp.json`, and scripts; `${CLAUDE_PLUGIN_DATA}` and `${CLAUDE_PROJECT_DIR}` also exist.
- `foundation:*` namespacing matches actual behavior (`plugin-name:component`; nested agent dirs namespace as `plugin:dir:name`).
- `hooks/hooks.json` is the documented conventional location (hooks may also be declared inline in `plugin.json`).
- Semver pinning by consumers via marketplace `ref` / `sha` is natively supported; explicit `version` in `plugin.json` controls update propagation. The distribution model is sound.
- Shipping `.mcp.json` at plugin root with env-var placeholders is the right mechanism for MCP config.
- The fail-open (advisory) / fail-closed (security) hook policy and the append-only naming contract are well-designed and implementable as stated.
