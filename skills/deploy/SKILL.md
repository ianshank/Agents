---
name: deploy
description: Generate a safety-railed deployment shell script (scripts/deploy.sh) with bash strict mode, a --dry-run mode, a confirmation gate before irreversible steps, rollback, and a health-check retry loop. Use this whenever the user wants a deploy script, a release/rollback workflow, deployment automation with a dry-run or confirmation prompt, a health-check-after-deploy step, or a safe repeatable deployment procedure. Config is passed as flags (app, artifact, health URL, environment) and lands as environment-overridable defaults — secrets are never inlined.
validator_version: '2.0'
compatibility: python>=3.10
version: 1.0.0
---

# deploy — deployment-script writer

Emit a `scripts/deploy.sh` whose value is its **safety structure**, not platform-specific deploy
logic: `set -euo pipefail`, a `--dry-run` mode that prints instead of acting, a confirmation gate
before irreversible steps, a health-check retry loop, a rollback path, and structured logging. You
fill in the per-step commands (clearly marked `TODO`); the scaffold guarantees the rails. Output
is byte-stable and ShellCheck-clean.

## 1. Preconditions (input contract)

- A target project directory exists.
- The deployment target is known well enough to pass as flags: app name, artifact/image
  reference, health-check URL, environment. Unspecified critical values default to `<...>`
  placeholders that the script refuses to run against (fail fast).
- Python 3.10+ (no third-party dependency — config is flag-driven, not detected).

## 2. Procedure (the E2E steps)

```bash
python scripts/gen_deploy.py --app <name> --artifact <ref> \
    --health-url <url> --environment <env> [--out <path>] [--stdout] [--check]
```

1. **Collect** the deployment config as flags. Do not put secrets on the command line or in the
   script — the script reads them from the environment at run time.
2. **Emit** `scripts/deploy.sh` with `build | release | rollback | health-check` subcommands, a
   `run` wrapper honouring `--dry-run`, a `confirm` gate (skipped by `--yes`/`--dry-run`), a
   `require` guard that aborts on unfilled `<placeholders>`, and a health-check retry loop.
3. **Fill in** each `TODO` step (replace the `true` placeholder with your platform's command).
4. **Review** and commit. Verify with `./scripts/deploy.sh --dry-run --yes release` — it should
   print the intended actions and change nothing.

## 3. Output contract (postconditions — what "done" means)

- `scripts/deploy.sh` is written (mode `+x`), starts with `#!/usr/bin/env bash`, sets
  `-euo pipefail`, ends in exactly one newline (LF), and re-renders **byte-identically**.
- `--dry-run` performs no side effects and exits 0; the confirmation gate aborts non-zero when
  declined; an unfilled placeholder value aborts non-zero; an unknown subcommand exits 2.
- No secret or credential is written into the script — all config is `${VAR:-default}` and
  overridable from the environment (ADR-0009 baseline).

## 4. Failure handling

- The `require` guard fails fast on any `<placeholder>` still present, so a half-configured deploy
  aborts instead of doing something surprising.
- `--check` is **advisory** (see §5), never a hard gate.

## 5. `--check` is advisory, not a gate

`--check` exits 1 when the committed script differs from a fresh render — an optional drift signal.
Because you extend the script with real deploy commands, **do not** wire `--check` into CI as a
blocking gate.

## 6. Validation gate (before declaring success)

You are **not done** until this exits 0:

```bash
python scripts/validate_skill.py --skill . --tier structural,behavioral
```

## 7. Examples

**Example 1 — dry run is side-effect-free**
`./scripts/deploy.sh --dry-run --yes release` prints `DRY-RUN: ...` lines for the release and
health-check steps and exits 0 without touching anything.

**Example 2 — fail fast on missing config**
Running `release` with `ARTIFACT` left at its `<artifact>` placeholder aborts non-zero with
`unconfigured value` — the deploy never proceeds half-configured.
