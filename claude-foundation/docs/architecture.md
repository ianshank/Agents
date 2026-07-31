# Architecture — claude-foundation

C4 model of the `foundation` plugin, as built. Diagrams are Mermaid and render
directly on GitHub. Names below reflect the shipped code (Python package
`foundation_tools`, hook scripts under `hooks/`), which supersedes the draft names in
the original plan.

## Level 1 — System Context

```mermaid
C4Context
  title System Context — claude-foundation
  Person(dev, "Developer", "Builds software across multiple repos")
  System(cf, "claude-foundation", "Versioned Claude Code plugin: skills, subagents, hooks, MCP template")
  System_Ext(cc, "Claude Code CLI", "Agent harness that loads the plugin")
  System_Ext(consumer, "Consumer Repos", "Agents, MouseDroid-AGI, piodeer, SQE platform")
  System_Ext(gh, "GitHub", "Hosting, marketplace distribution, CI (Actions)")
  System_Ext(api, "Anthropic API", "Model execution for evals and subagents")
  System_Ext(sc, "skill-creator plugin", "Official eval tooling: evals.json runs, grading.json")
  Rel(dev, cc, "Prompts / invokes foundation:* skills")
  Rel(cc, cf, "Installs & loads via marketplace add + plugin install")
  Rel(consumer, cf, "Pins a semver tag (marketplace ref/sha)")
  Rel(cf, gh, "CI validation, releases")
  Rel(cf, sc, "Delegates eval execution")
  Rel(sc, api, "Eval runs (isolated subagents)")
```

## Level 2 — Containers

```mermaid
C4Container
  title Containers — claude-foundation repository
  Container(manifest, "Plugin Manifest", ".claude-plugin/", "plugin.json + marketplace.json; discovery & versioning")
  Container(skills, "Skills", "Markdown + evals", "foundation:plan / code-review / test-first / c4-docs, each with evals/evals.json (skill-creator format)")
  Container(agents, "Subagents", "Markdown frontmatter", "explorer, test-runner; least-privilege tools; restricted plugin-agent frontmatter")
  Container(hooks, "Hooks", "Python + hooks.json", "pre_tool_guard.py, post_edit_verify.py, session_logger.py sharing hooks/_lib.py; env-var configured; JSONL logging")
  Container(tools, "foundation_tools", "Python 3.11+, stdlib logging", "Doc-derived schema validator, no-hardcode scanner, skill-creator eval-gate wrapper, JSONL log emitter")
  Container(ci, "CI Pipeline", "GitHub Actions", "Merge gate per PR; release gate on tags incl. backwards-compat fixture")
  Rel(ci, tools, "Executes")
  Rel(tools, skills, "Validates + gates evals")
  Rel(tools, agents, "Validates frontmatter")
  Rel(tools, hooks, "Tests + lints")
  Rel(hooks, tools, "Shares JSONL log format (foundation_tools.jsonlog / hooks/_lib.py)")
  Rel(manifest, skills, "Registers")
  Rel(manifest, agents, "Registers")
  Rel(manifest, hooks, "Registers")
```

## Level 3 — Components (foundation_tools package)

```mermaid
C4Component
  title Components — foundation_tools package
  Component(schemas, "schemas.py", "Python dataclass/typed models", "Doc-derived pinned models for plugin.json, marketplace.json, SKILL/agent frontmatter (incl. 1,536-char description cap, plugin-agent field restrictions); provenance in docs/sources.md")
  Component(validate, "validate.py", "Python, __main__ entry", "Walks the repo, validates every component against schemas.py; enforces plugin layout rules")
  Component(scan, "scan.py", "Python, __main__ entry", "No-hardcode scanner. Allowlist policy: full model IDs banned everywhere; aliases only in frontmatter model: fields; paths via ${CLAUDE_PLUGIN_ROOT}-style vars only")
  Component(evalgate, "eval_gate.py", "Python, __main__ entry", "Thin wrapper: invokes skill-creator evals headlessly, parses grading.json, gates release tags on 100% assertion pass")
  Component(jsonlog, "jsonlog.py", "Python stdlib logging", "Shared JSONL structured-log emitter for tools; hooks mirror it via dependency-free hooks/_lib.py")
  Component(compat, "backwards_compat.py", "Python, __main__ entry", "Diffs live skill/agent/hook names against tests/backwards_compat_baseline.json; fails release gate on removal without a major version bump (ADR 0004); --update regenerates the baseline pre-release")
  Rel(validate, schemas, "Uses")
  Rel(scan, jsonlog, "Emits findings")
  Rel(evalgate, jsonlog, "Emits run logs")
  Rel(validate, jsonlog, "Emits results")
  Rel(compat, schemas, "Uses")
  Rel(compat, jsonlog, "Emits results")
```

### Hook scripts (companion to Level 3)

The three hook scripts are intentionally **not** part of `foundation_tools`: they must
run with zero third-party dependencies in arbitrary consumer environments
(see [ADR 0003](adr/0003-eval-integration-and-stdlib-logging.md)).

| Script | Event | Fail mode |
|---|---|---|
| `hooks/pre_tool_guard.py` | PreToolUse | Closed — deny on error or match ([ADR 0002](adr/0002-hook-fail-modes.md)) |
| `hooks/post_edit_verify.py` | PostToolUse | Open — advisory, never blocks |
| `hooks/session_logger.py` | Tool lifecycle | Open — advisory, never blocks |
| `hooks/_lib.py` | (shared) | stdin JSON parsing, env config, JSONL logging |
