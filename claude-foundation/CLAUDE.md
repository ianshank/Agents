# CLAUDE.md

## Build/Test Commands

```bash
pytest                                # unit tests (hooks, validator, eval gate)
ruff check .                          # lint
ruff format --check .                 # formatting
mypy tools                            # strict type checking
python -m foundation_tools.validate   # frontmatter + manifest schema validation
python -m foundation_tools.scan       # no-hardcode scanner (allowlist policy)
python -m foundation_tools.backwards_compat  # append-only component-name gate
claude plugin validate .              # official plugin structure checker
bash tests/smoke/install_smoke.sh     # install smoke test (--plugin-dir fast path)
```

Release gate (before tagging, also nightly): `python -m foundation_tools.eval_gate`
plus `python -m foundation_tools.backwards_compat` (ADR 0004). Behavioral evals never
gate merges.

Before removing or renaming a skill/agent/hook alongside a major version bump, run
`python -m foundation_tools.backwards_compat --root . --update` and commit the
resulting `tests/backwards_compat_baseline.json` diff in the same PR as the bump —
the gate warns if the baseline is stale relative to the current major, but does not
block on it.

## Architecture Decisions

- [ADR 0001](docs/adr/0001-plugin-plus-marketplace-packaging.md): packaged as a plugin
  plus self-hosted marketplace, not a copy-template; consumers pin semver tags via
  marketplace `ref`/`sha`.
- [ADR 0002](docs/adr/0002-hook-fail-modes.md): `pre-tool-guard` fails closed (exit 2 /
  `permissionDecision: "deny"`); `post-edit-verify` and `session-logger` fail open
  (always exit 0).
- [ADR 0003](docs/adr/0003-eval-integration-and-stdlib-logging.md): skill-creator evals
  gated by the thin `foundation_tools.eval_gate` wrapper (release-blocking only);
  stdlib-`logging` JSONL instead of structlog so hooks run dependency-free.
- [ADR 0004](docs/adr/0004-backwards-compat-manifest-diff.md): implements ADR 0001 pt.
  4's append-only contract via `foundation_tools.backwards_compat`, diffing a
  checked-in `tests/backwards_compat_baseline.json` against the live skill/agent/hook
  surface; removals without a major version bump fail the release gate, additions
  never do.

## Compatibility Contract

- Component names (skills, subagents, hooks) are **append-only within a major
  version**; renames/removals require a major bump and a manifest-diff check enforces
  this at release time.
- The plugin name `foundation` owns the `foundation:*` namespace; the repository name
  (`claude-foundation`) is only the marketplace name.

## Known Limitations

- Behavioral skill evals are non-deterministic and require Anthropic API access and
  credits; they run in the release gate (and nightly), never per-PR.
- Hooks assume a POSIX environment, or Windows with Python 3.11+ on `PATH`; hook
  scripts are stdlib-only by design (ADR 0003).
