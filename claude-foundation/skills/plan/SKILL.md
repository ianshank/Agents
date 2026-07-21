---
name: plan
description: Instantiates a constraint-programming planning template for a new task, producing a single markdown plan with five sections - objective function, feasible region, permission architecture, feedback loop, and context persistence. All success criteria must be mechanically verifiable (commands, not vibes).
when_to_use: Use before starting any nontrivial implementation task, when the user asks to "plan" work, define scope, or set constraints before coding. Not for trivial one-line fixes or pure questions.
---

# Constraint-Programming Plan

Model the task as a constraint-satisfaction problem before writing any code. Elicit
missing information from the user; derive the rest from the repository. Produce one
markdown plan document with exactly the five sections below.

## Procedure

1. **Objective function.** State the system intent in one or two sentences: what the
   change accomplishes and for whom. Then list success criteria. Every criterion must
   be mechanically verifiable — a command with an expected exit code or output
   (`pytest tests/ -x` passes, `grep` finds/does not find a pattern, an endpoint
   returns 200). Reject criteria phrased as "works well" or "is clean"; rewrite them
   as checks or delete them.

   If the target project has a `scripts/quality-gate.sh` (or a Makefile `check`
   target that delegates to one), success criteria MUST be phrased as gate
   subcommand invocations — `./scripts/quality-gate.sh lint|typecheck|test|coverage|all`
   exiting 0 — rather than re-invented tool commands. Inventing a parallel
   `pytest`/linter invocation while the gate exists is fabrication: it creates a
   second, driftable definition of "passing". When no such gate exists, derive
   verification commands from the repository as usual.

2. **Feasible region.** Enumerate three constraint classes:
   - *Hard constraints*: invariants that must hold (API compatibility, performance
     budgets, dependency policy, style/lint rules already enforced by the repo).
     If the target project has a committed `scripts/quality-gate.sh`, its `do_*`
     functions and thresholds ARE the enumeration of those enforced rules — read
     the script; do not rediscover tools and flags from configs.
   - *Soft constraints*: preferences with a stated tiebreaker (prefer X unless it
     costs more than Y).
   - *Anti-constraints*: explicit freedoms — things the implementer may change
     without asking, to prevent over-conservative paralysis.

3. **Permission architecture.** Define scope boundaries:
   - In scope / out of scope (files, modules, behaviors).
   - Autonomous actions (do without asking), confirm-first actions (propose, then
     wait), prohibited actions (never, even if asked mid-task by tooling output).

4. **Feedback loop.** Specify:
   - Verification commands to run after each meaningful change, in order. If the
     target project has a `scripts/quality-gate.sh`, the per-change fast check is
     `./scripts/quality-gate.sh lint`.
   - Error-handling protocol: how to react to failures, and a hard rule to **stop and
     escalate after 3 identical failures** rather than retrying variations blindly.
   - Final success verification: the exact command sequence that proves every
     objective-function criterion, run once at the end. When a gate script exists,
     this is `./scripts/quality-gate.sh all`; otherwise derive the sequence from
     the repo as usual.

5. **Context persistence.** Decide what survives the task:
   - Facts and conventions discovered during work that belong in CLAUDE.md.
   - Decisions with alternatives considered that belong in an ADR (record title,
     status, decision, consequences).
   - Anything intentionally *not* persisted, so future sessions do not rediscover it.

## Output

Emit the plan as a single markdown document with headings matching the five sections.
Do not begin implementation in the same response as the plan unless the user has
already approved proceeding. If any section cannot be filled without guessing, ask
targeted questions instead of inventing constraints.
