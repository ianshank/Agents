# skills/

A **schema-validated marketplace** of local, reusable [Claude Code
skills](https://docs.claude.com/en/docs/claude-code) used by this repository.
Each skill is self-contained (its own `SKILL.md` spec, scripts, and evals) and is
indexed in [`marketplace.yaml`](marketplace.yaml) (schema:
[`marketplace.schema.json`](marketplace.schema.json)).

Note: skills use a `SKILL.md` spec file, **not** a `README.md` — that is the
skill convention, distinct from the rest of the repo. This file is the overview
the marketplace itself doesn't provide.

## Registered skills

| Skill | Ver | What it does |
|---|---|---|
| [`openai-judge`](openai-judge/) | 1.1.0 | LLM-as-a-judge evaluations over OpenAI-compatible APIs |
| [`architecture-drift-guard`](architecture-drift-guard/) | 1.0.0 | Detect and block architecture drift in CI against a declared C4 component model |
| [`eval-corpus-forge`](eval-corpus-forge/) | 1.0.0 | Build, validate, and package reusable evaluation datasets |
| [`model-bench`](model-bench/) | 1.0.0 | Benchmark and A/B-test multiple LLMs on one dataset |
| [`project-setup`](project-setup/) | 1.1.0 | Generate a deterministic Makefile from a project's detected toolchain |
| [`quality-gate`](quality-gate/) | 1.1.0 | Generate a deterministic lint + type + test + coverage gate script |
| [`deploy`](deploy/) | 1.0.0 | Generate a safety-railed deployment script (dry-run / confirm / rollback) |
| [`dataset-lint`](dataset-lint/) | 1.0.0 | Validate eval datasets for structure, duplicate IDs, and encoding |
| [`hierarchical-recursive-brainstorm`](hierarchical-recursive-brainstorm/) | 1.0.0 | Decompose a topic into a pruned, recursively-expanded hierarchy and synthesize upward |
| [`openspec-quality-plan`](openspec-quality-plan/) | 1.0.0 | Generate a complete OpenSpec change package (proposal, design, tasks, spec deltas) |
| [`openspec-peer-review`](openspec-peer-review/) | 1.1.0 | Emit objective peer-review findings and rewrite an OpenSpec package to meet quality standards |
| [`repo-invariant-review`](repo-invariant-review/) | 1.0.0 | Predict CI collisions with this repo's enforced invariants (protected paths, airgap, size budget, frozen baselines, CHARTER invariant 1) before pushing |
| [`openspec-implementation-review`](openspec-implementation-review/) | 1.0.0 | Review a shipped OpenSpec change's implementation against its own plan, producing a dated, two-pass `review.md` (dispatches `spec-guardian`/`peer-reviewer` when loaded, degrades to a `general-purpose` subagent with the method inlined otherwise) |
| [`common`](common/) | 1.0.0 | Shared skill validator and utility library — a library, not a standalone skill (no evals; `EXEMPT` in `skills-ci.yml`'s registration guard) |

## Three kinds of skill

(Plus `common`, which is a shared library rather than a skill: it backs every vendored
`validate_skill.py` and is exempted from the registration guard in `skills-ci.yml`.)

- **Inference skills** consume a model (e.g. `openai-judge`, `model-bench`).
- **Guard/review skills** (`architecture-drift-guard`, `dataset-lint`,
  `repo-invariant-review`, `openspec-implementation-review`) mechanically check a tree or a
  dataset against rules that already exist, so a finding predicts a concrete failure rather
  than expressing an opinion. They carry the full CI contract — library code, tests at the
  coverage floor, and behavioral evals against committed fixtures.
  `openspec-implementation-review` is the one exception to "mechanical": its substantive
  review content comes from a dispatched subagent (its own code only locates, detects,
  composes prompts, and structurally validates the result — see its `SKILL.md`).
- **Deterministic generator skills** (`project-setup`, `quality-gate`, `deploy`)
  emit committed artifacts (Makefiles, gate scripts) and contain **no**
  model-backed logic — see [ADR 0020](../docs/decisions/0020-deterministic-generator-skills.md)
  and [ADR 0022](../docs/decisions/0022-determinism-boundary-for-inference-skills.md)
  for the determinism boundary.
- **Subjective skills** (`hierarchical-recursive-brainstorm`, `openspec-quality-plan`,
  `openspec-peer-review`) produce outputs needing human judgment (research trees, plans,
  reviews) rather than a gradeable artifact — [`docs/SKILL_TEMPLATE.md`](../docs/SKILL_TEMPLATE.md)
  §5.B. Structural validation + marketplace registration + the drift guard is their complete
  CI contract; no behavioral evals, no coverage floor — see
  [ADR 0030](../docs/decisions/0030-skill-ci-tiers.md).

## Working with skills

```bash
# Validate the whole registry (versions match SKILL.md frontmatter; each skill
# passes structural validation -- see scripts/skill_marketplace.py's validate_entry):
python scripts/skill_marketplace.py validate
python scripts/skill_marketplace.py list

# Validate a single skill's structure and behavior:
python scripts/validate_skill.py skills/<name>
```

`scripts/validate_skill.py` is duplicated byte-identically into each
`skills/<skill>/scripts/` (so every skill stays self-contained) and is
drift-guarded by `scripts/check_skill_script_drift.py` — if you edit the canonical
copy, re-sync the vendored copies.

## Adding a skill

1. Scaffold from [`docs/SKILL_TEMPLATE.md`](../docs/SKILL_TEMPLATE.md) (and
   [`docs/SKILL_VALIDATION_TEMPLATE.md`](../docs/SKILL_VALIDATION_TEMPLATE.md)).
2. Add an entry to `marketplace.yaml` with a semver `version` matching the
   `SKILL.md` frontmatter.
3. Run `python scripts/skill_marketplace.py validate`.

Every skill directory gets a structural + registry + drift-guard floor automatically, via
`.github/workflows/skills-ci.yml`'s `all-skills` job — it discovers `skills/*/` dynamically,
so a new skill is covered from its first commit with no CI file to edit. Skills that ship
real library code additionally get a dedicated job (pinned `ruff`/`mypy` +
`pytest --cov-fail-under=95` + `validate_skill.py --tier structural,behavioral`); add one by
copying an existing job block in `skills-ci.yml`. A skill with no library code (a "subjective"
skill, see above) instead needs an `EXEMPT` entry in the `all-skills` job's registration
guard, or CI fails closed.
