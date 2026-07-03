# 0002 — Hook fail modes: security guard fails closed, advisory hooks fail open

- Status: **Accepted.**
- Date: 2026-07-03
- Related: `docs/plans/claude-foundation/PLAN.md` in `ianshank/Agents` (§1.3 invariant 3,
  §2.1 baseline table); REVIEW.md finding m4 (concrete blocking mechanics);
  ADR 0003 (dependency-free hook logging).

## Context

The plugin ships three hooks: `pre-tool-guard` (PreToolUse security check),
`post-edit-verify` (PostToolUse lint/typecheck of touched files), and `session-logger`
(JSONL audit trail). A hook that errors can either block the tool call it intercepts or
let it proceed. Blocking on error is correct for a security control (an attacker or a
bug must not bypass the guard by crashing it) and wrong for advisory checks (a broken
linter config must not paralyze every edit in every consumer repo). Claude Code defines
the concrete mechanics: exit code 2 blocks with stderr fed back to Claude; exit 0 lets
stdout be parsed as JSON control output; other exit codes are non-blocking errors.

## Decision

1. **`pre-tool-guard` fails CLOSED.** Any matched deny rule (built-in `.env`-read and
   write-scope rules, plus `CLAUDE_FOUNDATION_GUARD_DENY_GLOBS` extras) — and equally
   any internal error (unparseable stdin, unreadable config, unexpected exception) —
   results in a deny. Mechanics, either of:
   - exit code **2** with the reason on **stderr** (fed back to Claude); or
   - exit code **0** with stdout JSON:

     ```json
     {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                             "permissionDecision": "deny",
                             "permissionDecisionReason": "<reason>"}}
     ```

   The top-level exception handler forces the deny path, so a crash can never
   silently allow the tool call.
2. **`post-edit-verify` fails OPEN.** It always exits **0**. Verification findings are
   returned as `hookSpecificOutput.additionalContext` in stdout JSON so Claude sees
   them; they never block the edit. Errors (missing `CLAUDE_FOUNDATION_VERIFY_CMD`
   tool, command timeout, internal exception) are logged when
   `CLAUDE_FOUNDATION_LOG_DIR` is set, then swallowed — still exit 0.
3. **`session-logger` fails OPEN.** Pure observer: exit **0** always, no stdout
   control output, all errors swallowed after best-effort logging.
4. **No further fail-closed hooks without a new ADR.** The plan's permission
   architecture requires explicit confirmation for any hook that blocks tool use
   beyond `pre-tool-guard`; this ADR records that boundary.

## Consequences

- Unit tests assert the fail modes explicitly: the guard's error paths must produce
  exit 2 (or a `"deny"` decision), and the advisory hooks' error paths must produce
  exit 0 — a hook test encoding the opposite behavior is a bug in the test.
- A misconfigured guard (e.g. malformed deny glob) degrades to "deny more", never
  "allow more"; the cost is occasional false blocks, surfaced via stderr reasons.
- Advisory hook failures are invisible unless `CLAUDE_FOUNDATION_LOG_DIR` is set;
  operators who need an audit trail must set it.
