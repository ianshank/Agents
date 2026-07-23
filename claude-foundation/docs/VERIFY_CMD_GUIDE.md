# CLAUDE_FOUNDATION_VERIFY_CMD Guide

`CLAUDE_FOUNDATION_VERIFY_CMD` is a configuration environment variable that enables automatic, advisory feedback on every file edit or write operation intercepted by the Claude Code plugin.

This documents how it works, how to configure it for different programming languages, and how it interacts with enterprise security.

## How it works

When a file is modified (via `Edit` or `Write` tools), the `post_edit_verify.py` hook is triggered by the Claude Code lifecycle runner if registered under `PostToolUse` in `hooks.json`.

1. If `CLAUDE_FOUNDATION_VERIFY_CMD` is set, the hook replaces `{file}` in the configured command with the absolute path of the touched file.
2. The command is executed as a subprocess.
3. The hook captures stdout and stderr of the command.
4. Any output is returned as `additionalContext` back to the Claude agent.
5. The hook **fails open** (always exits with code `0`), meaning that a failing linter or compiler will never block your workflow—it only surfaces the findings as warning context to the agent, allowing it to self-correct.

## Recommended Commands by Stack

### Python
```bash
export CLAUDE_FOUNDATION_VERIFY_CMD="python -m ruff check {file}"
```
Alternatively, if you also want typing validation (note: might be slower):
```bash
export CLAUDE_FOUNDATION_VERIFY_CMD="python -m ruff check {file} && mypy {file} --no-error-summary"
```

### JavaScript / TypeScript
```bash
export CLAUDE_FOUNDATION_VERIFY_CMD="npx eslint {file}"
```

### Go
```bash
export CLAUDE_FOUNDATION_VERIFY_CMD="go vet {file}"
```

## Enterprise Security & allowManagedHooksOnly

In locked-down enterprise environments, security policies often enforce:
- `allowManagedHooksOnly: true`

This blocks any custom local hooks from executing. However, hooks provided by **force-enabled managed plugins** (like the `foundation` plugin) are permitted to load and run. 

Because `post_edit_verify.py` is part of the managed `foundation` plugin, it runs successfully even under strict enterprise policies. Enforcing per-file linting is then achieved simply by configuring the `CLAUDE_FOUNDATION_VERIFY_CMD` environment variable in the developer's environment (or globally via system profile defaults).

## Performance Guidelines

Since the hook runs on every edit, follow these guidelines to keep your agent session responsive:
- Keep the verification command lightweight. It should ideally complete in **under 2 seconds**.
- Avoid running project-wide test suites or heavy linters. Restrict checks specifically to the touched `{file}`.
- If a command is slow, wrap it in a fast pre-check (e.g. exit early if file has certain extension).
