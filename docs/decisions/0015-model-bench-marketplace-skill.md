# 0015 — model-bench marketplace skill (wraps F-024/F-025)

- Status: **Accepted.** New skill; reuses existing library features, adds no harness code.
- Date: 2026-06-30
- Related: F-024 (multi-model comparison), F-025 (A/B campaigns), F-027 (model target),
  F-023 (marketplace), F-029, `skills/model-bench/`, `src/eval_harness/cli.py`.

## Context

Multi-model comparison (F-024) and A/B campaigns (F-025) shipped as library functions and
`eval-harness` CLI subcommands, but there was no packaged, discoverable skill that presents
"benchmark/A-B-test several models" as a first-class capability. `progress.md` carried this as
the standing optional follow-up ("a marketplace skill wrapping F-024/F-025"). With the real
model-backed target (F-027) now available, such a skill can drive live models.

## Decision

1. **A new v2.0-convention skill** `skills/model-bench/` (SKILL.md with `validator_version:
   '2.0'`, `scripts/run.py`, vendored `scripts/validate_skill.py`, `evals/` + fixtures,
   `references/`, `tests/`, `ruff.toml`, `.gitignore`) — the same shape as `eval-corpus-forge`.
2. **The runner is a thin forwarder, not a reimplementation.** `scripts/run.py` validates the
   subcommand (`compare` | `campaign`) and forwards verbatim to `eval_harness.cli.main`, which
   already owns arg parsing and reuses `run_comparison` / `record_run` / `analyze`
   (F-024/F-025). The skill adds packaging, documentation, ready-to-run fixtures, and offline
   evals — no orchestration logic.
3. **Offline, deterministic fixtures.** `evals/fixtures/{compare,campaign}.yaml` use `echo`
   targets so the behavioral evals run with no network or credentials. The SKILL.md and
   `references/usage.md` show swapping a target to `{type: model, ...}` (F-027) to benchmark a
   real model, with credentials via `${VAR}` interpolation — never embedded.
4. **CI.** A `model-bench` job is added to `skills-ci.yml`. Unlike the other (isolated) skill
   jobs it installs the repo packages (`-e ../..` + `-e ../../agent-core`), because this skill
   wraps the harness by design; the fixtures need no provider extras.
5. **Registered** in `skills/marketplace.yaml` with a version matching the SKILL.md frontmatter
   (semver match enforced by `scripts/skill_marketplace.py validate`). The canonical
   `validate_skill.py` is vendored byte-for-byte (skill-script drift guard) and reused
   read-only by the F-029 validator.

## Consequences

- **No harness changes.** The skill is purely additive; the eval engine, config schema, and
  the `compare`/`campaign` CLI are untouched.
- **No hard-coded values.** Models, datasets, ranking score/metric, and campaign power floor
  come from the config; credentials from the environment.
- **Tested offline.** `skills/model-bench/tests/` cover the forward, usage-error, and
  import-error branches and drive real `compare`/`record`/`analyze` over the echo fixtures
  (100% coverage on the runner); the skill's structural+behavioral evals pass; F-029 asserts
  the layout, the forward, and the marketplace registration.
- **Caveat.** Because the skill wraps the harness, its CI job is not import-isolated like the
  others — that is inherent to a skill whose whole purpose is to orchestrate the engine.
