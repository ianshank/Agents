# 0020 — Deterministic generator skills (project-setup / quality-gate / deploy)

- Status: **Accepted.**
- Date: 2026-07-16
- Related: `skills/project-setup/`, `skills/quality-gate/`, `skills/deploy/`,
  `skills/marketplace.yaml`, `.github/workflows/skills-ci.yml`,
  `scripts/check_skill_script_drift.py`, ADR 0009 (no hard-coded secrets, config-driven
  defaults), ADR 0017 (claude-foundation reconciliation), ADR 0019 (size-budget gate).

## Context

The repo hosts two kinds of skills. The `skills/*` action skills (architecture-drift-guard,
eval-corpus-forge, model-bench, openai-judge) are **deterministic**: they ship `scripts/` and run
them, and architecture-drift-guard states the design law outright — *"The blocking gate is
deterministic code — a model is never in its decision path."* The `claude-foundation/skills/*`
skills (c4-docs, code-review, plan, test-first) are **inference-heavy**: they describe a procedure
the model re-derives on every invocation.

Many routine engineering chores — setting up a project's task runner, running its quality gate,
deploying it — are *mechanical*. Re-deriving them by inference each session is slower, costs
tokens, and is non-reproducible: two runs can produce two different command sets. Worse, the
project's checks lived only in CI YAML (`quality-gates.yml`) plus scattered `scripts/*.py`, with
**no `Makefile`**, so a developer could not run the same gate locally with one command, and the
Makefile-vs-CI (or local-vs-CI) definitions could silently drift apart.

## Decision

Add three **generator skills** that turn implicit, re-inferred procedure into explicit, committed,
deterministic artifacts for a Python project. The model is invoked **once**, at generation time;
the emitted artifact then runs with zero inference.

| Skill | Emits | Role |
|---|---|---|
| `project-setup` | `Makefile` | Orchestration/index: `help/install/format/lint/typecheck/test/coverage/check/build/clean/deploy` |
| `quality-gate` | `scripts/quality-gate.sh` | Single source of truth for lint + type + test + coverage; run locally and in CI |
| `deploy` | `scripts/deploy.sh` | Safety-railed deploy scaffold: strict mode, dry-run, confirm gate, rollback, health check |

### Design laws (enforced by tests in each skill)

1. **Deterministic, byte-stable output.** Generation is a pure function of observable inputs
   (`pyproject.toml` tables, marker files, layout, or explicit flags). No timestamps or volatile
   content, stable ordering, LF endings, `.as_posix()` paths — re-running on unchanged input yields
   a byte-identical file (asserted).
2. **Never fabricate.** A tool or config that is absent yields a *missing* target/step, never a
   guessed command. Empty-but-present TOML tables (`[tool.ruff]`) count as configured (presence,
   not truthiness).
3. **Composition, one source of truth.** When `scripts/quality-gate.sh` exists, the Makefile's
   gate targets *delegate* to it rather than duplicating commands; the Makefile's `deploy` target
   delegates to `scripts/deploy.sh`. CI runs the same `quality-gate.sh` — so local == CI by
   construction, not by discipline.
4. **`--check` is advisory, not a gate.** Every generator can diff the committed artifact against a
   fresh render, but because these artifacts are *scaffolds users extend*, `--check` is an optional
   drift signal — never wired as a blocking CI gate by default. (This is the key difference from
   `mermaid_gen --check`, whose artifact is fully derived and not hand-edited.)
5. **No hard-coded secrets (ADR 0009).** `deploy.sh` reads all config — app, artifact, health URL,
   environment — from `${VAR:-default}` overrides; nothing sensitive is inlined. A `require` guard
   fails fast on any unfilled `<placeholder>`.
6. **Shell safety.** Generated shell is `set -euo pipefail` and ShellCheck-clean; `deploy.sh` adds
   `--dry-run`, a confirmation gate before irreversible steps, and a health-check retry loop.
7. **Proven, not just parsed.** Validation runs the artifacts for real (not only `bash -n`/`make
   -n`): the gate passes on a clean fixture and fails on a broken one; the deploy dry-run makes no
   changes and the confirm gate aborts when declined.

### Repo integration

Each skill matches the established layout (`SKILL.md`, `ruff.toml` extending the root, a
byte-identical vendored `scripts/validate_skill.py` registered in `check_skill_script_drift.py`,
`evals/`, `tests/`). Registered in `skills/marketplace.yaml`; a per-skill CI job in `skills-ci.yml`
runs pinned `ruff==0.15.20` / `mypy==2.1.0`, `pytest --cov ... --cov-fail-under=95`, and the
structural+behavioral self-check across Python 3.10–3.12.

## Consequences

- Routine tasks become one deterministic command (`make test`, `./scripts/quality-gate.sh all`)
  instead of re-inference; the artifacts are reviewable diffs, not model output.
- The Makefile↔CI drift class is removed for adopters: the gate script is the single definition
  both call.
- Cost: three more skills to maintain, each at the repo's ≥95 % branch-coverage floor. Detection is
  duplicated (minimally) per skill rather than shared, preserving the deliberate self-containment
  the skill-script drift guard is built around.
- **Out of scope:** this ADR does not rewire the repo's own working `quality-gates.yml` to call a
  generated script; the skills emit artifacts (and an optional CI snippet) for *target* projects.

## Alternatives considered

- **Keep re-inferring each run** — rejected: non-reproducible, slower, token-heavy for mechanical
  work; contradicts the repo's stated determinism law.
- **`tox` / `nox`** — good task runners, but add a dependency and a second config surface; the user
  asked for a plain Makefile + shell scripts (POSIX, zero-install).
- **`pre-commit`** — solves local hooks, not the single local==CI gate command or deployment.
- **`just`** — ergonomic, but non-standard and not preinstalled; Make is ubiquitous.
- **A template engine (cookiecutter/copier)** — overkill for single files and would still need the
  same detection; a small pure renderer with unit tests is simpler and byte-stable.

## References

Informed by a deep-research pass (harness task `w0y6f1biq`) whose adversarially-verified synthesis
is attached to the PR. Canonical sources consulted:

- Anthropic, *Equipping agents for the real world with Agent Skills* — skills bundle executable
  scripts and should prefer deterministic code over re-inference.
- *Your Makefiles are wrong* (tech.davis-hansson.com) — `.ONESHELL`, `.DELETE_ON_ERROR`, strict
  `.SHELLFLAGS`, and self-documenting targets.
- *Local-first CI/CD with Makefiles* (shipyard.build) — one command that runs identically locally
  and in CI.
- *Use Bash Strict Mode* (redsymbol.net) — `set -euo pipefail` rationale and pitfalls.
