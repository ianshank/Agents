---
name: code-review
description: Runs a security and quality review checklist over a diff or named files in an isolated forked subagent. Covers injection, secrets, authz/authn, error handling, resource leaks, concurrency, compatibility, test coverage, and hardcoded config. Returns severity-ranked findings with file:line and a blocking/non-blocking/clean verdict. Read-only - never edits code or proposes inline fixes.
when_to_use: Use when the user asks to review changes, audit a diff or PR, or check code for security or quality issues before merge. Not for writing new code or fixing issues.
context: fork
allowed-tools: Read, Grep, Glob
---

# Code Review (Forked, Read-Only)

Review the given diff or files against the checklist below. This skill runs in an
isolated fork with read-only tools: do not edit files, do not propose inline patches,
do not run commands. Return findings only.

## Procedure

1. Identify the review target: the provided diff, the named files, or (if neither)
   the files the caller describes. Read each changed file in full, not just hunks —
   context outside the diff often invalidates or confirms a finding.

2. Evaluate every item on the checklist against the changed code:
   - **Injection / input validation**: SQL, shell, path, template, deserialization;
     untrusted input reaching a sink without sanitization.
   - **Secrets / credentials**: keys, tokens, passwords, connection strings committed
     in code or test fixtures.
   - **Authz / authn changes**: new endpoints or paths that bypass existing checks;
     weakened permission logic.
   - **Error handling**: swallowed exceptions, fail-open behavior where fail-closed is
     required (and vice versa), missing error paths.
   - **Resource leaks**: unclosed files, sockets, connections, subscriptions; missing
     finally/defer/with equivalents.
   - **Concurrency**: shared mutable state, race conditions, missing locks or atomics,
     deadlock-prone lock ordering.
   - **Backwards compatibility**: changes to public function signatures, wire formats,
     schemas, CLI flags, or config keys that break existing callers.
   - **Test coverage**: changed behavior with no corresponding test change; tests
     deleted or weakened.
   - **Hardcoded values**: literals (URLs, ports, timeouts, limits, paths) that belong
     in config or environment.

3. For each finding, record: severity (critical / high / medium / low), `file:line`,
   a one-sentence defect statement, and a concrete failure scenario (the input or
   sequence of events that makes it go wrong). No finding without a scenario.

4. Discard findings you cannot tie to a specific line and scenario. Do not pad the
   report with style nits unless nothing else was found, and label them as such.

## Output

- Findings ranked by severity, highest first, in the format:
  `[SEVERITY] file:line — defect statement. Scenario: ...`
- End with exactly one verdict line:
  - `Verdict: blocking` — at least one critical or high finding.
  - `Verdict: non-blocking` — only medium/low findings.
  - `Verdict: clean` — no findings.
- Never include patches, rewritten code, or fix suggestions beyond naming the defect;
  the caller decides remediation outside the fork.
