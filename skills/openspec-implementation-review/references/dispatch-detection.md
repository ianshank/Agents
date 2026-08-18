# Detecting the dispatch path

`claude-foundation/` is a **staging directory** (ADR 0028), not an installed plugin in this
repo's own sessions. Its two charter files being present on disk proves they exist to
*stage*, never that they are *loaded* into whatever session is running this skill. Conflating
those two facts is exactly the failure mode this module exists to avoid.

`implreview.detect.detect_dispatch_path` checks what a script actually can:

1. **Do both charter files exist**, and does `claude-foundation/.claude-plugin/plugin.json`
   look like a real manifest (`name: "foundation"`)? Absence of either is conclusive — the
   plugin path cannot be available regardless of session state.
2. **Is `CLAUDE_PLUGIN_ROOT` set, and does it resolve to this repo's `claude-foundation/`
   directory?** This is the environment variable Claude Code populates for a plugin's own
   hooks/scripts while they run — see `claude-foundation/hooks/hooks.json`, which reads it
   directly (`"${CLAUDE_PLUGIN_ROOT}/hooks/pre_tool_guard.py"`). If it is set and resolves to
   this same staging directory, that is genuine evidence this process is executing *as* the
   foundation plugin. It is not, however, evidence about an arbitrary *other* subprocess the
   calling agent might separately run via its own shell tool — the variable is scoped to the
   plugin's own invocation, not exported session-wide.

Recommendation is `plugin` **only** when both hold; otherwise `degraded`, conservatively —
presence on disk alone is never treated as sufficient.

## The signal is necessary, not sufficient — corroborate before dispatching by name

Even a `plugin` recommendation is a filesystem-level proxy, not proof that `spec-guardian`/
`peer-reviewer` are actually among *your* (the calling agent's) dispatchable subagent types —
that fact lives in the agent harness, not on disk, and no subprocess can see it. Before
dispatching either charter by name, independently confirm they appear in your own available
subagent types — check whatever your harness exposes for that (a tool-search over dispatch
tools, a `Task`-style tool's `subagent_type` enum, or simply attempting the dispatch and
catching an unknown-type failure) — and only then proceed, or override with `plan
--force-path plugin` if you have already confirmed it some other way.

## Empirically, in this repo, today

Both this skill's own dogfood run and the orchestrating session that merged
`add-foundation-reviewer-charters` (Phase 4) land on `degraded`: no session working this repo
directly has `CLAUDE_PLUGIN_ROOT` set, because ordinary sessions never start with `claude
--plugin-dir claude-foundation`. `openspec/AGENTS.md`'s staging precondition says this
explicitly, and `tests/test_detect.py` asserts it against the real process environment, not
just a fixture. **This means the degraded path is the one that actually runs in practice, not
a rare fallback** — `implreview.prompts.build_degraded_prompt` is written to be fully
self-contained for exactly this reason, and it is the path exercised by this skill's own
evals (`evals/evals.json`'s `compose-appends-without-clobbering` case runs the degraded path
twice, end to end, via two real subprocess invocations).

## What this module cannot do, and does not pretend to

It cannot dispatch anything itself — `spec-guardian`, `peer-reviewer`, and `general-purpose`
are tools of the calling agent's own harness, unreachable from a Python subprocess. It cannot
observe the calling agent's own subagent-type list. It can only report the narrow, real
signal above and recommend conservatively. `SKILL.md` §2 step 2 names the corroboration this
module cannot perform itself; do not skip it because the tool's own output looked confident.
