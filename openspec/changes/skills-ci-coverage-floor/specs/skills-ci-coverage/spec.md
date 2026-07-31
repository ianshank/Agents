# Spec delta: skills-ci-coverage

Capability: every registered skill directory receives CI on its own changes, at a tier
matched to whether it ships library code. Compiles down to F-050 in `features.yaml` +
`scripts/validations/F_050.py`.

## ADDED Requirements

### Requirement: Every skill directory triggers CI on its own changes

`skills-ci.yml` SHALL trigger on any change under `skills/**`, rather than on a per-skill
allowlist. A skill directory SHALL NOT be reachable-but-untriggered: the workflow's `paths:`
filter SHALL NOT enumerate individual skill paths, because a filter that must be
independently kept in sync with the skill directory set has already been observed to drift
(`dataset-lint` was omitted from a 7-entry list while its dedicated job existed).

#### Scenario: A change to a skill with no dedicated job still triggers CI

- **WHEN** a PR touches only `skills/<any-skill>/**` for a skill that has no dedicated
  lint/type/pytest job in `skills-ci.yml`
- **THEN** the `skills CI` workflow still runs, because the trigger is not conditioned on the
  skill having a job

#### Scenario: Editing a vendored validator copy triggers the guard that checks it

- **WHEN** a PR edits `skills/<any-skill>/scripts/validate_skill.py`
- **THEN** `check_skill_script_drift.py` runs as part of that PR's CI, because the drift guard
  is no longer reachable only through an unrelated `scripts/**` change

### Requirement: Every skill directory gets a structural validation floor

An `all-skills` CI job SHALL discover every `skills/*/` directory dynamically — never from a
fixed list — and SHALL run `validate_skill.py --tier structural` against each one,
accumulating failures across all discovered skills rather than stopping at the first
failure.

#### Scenario: A skill added without a dedicated job is still structurally validated

- **WHEN** a new skill directory is added under `skills/` with no corresponding job in
  `skills-ci.yml`
- **THEN** `all-skills` still runs `validate_skill.py --tier structural` against it, because
  discovery is a glob over `skills/*/`, not a job-name lookup

#### Scenario: One failing skill does not hide a second

- **WHEN** two distinct skill directories both fail `validate_skill.py --tier structural` in
  the same CI run
- **THEN** the job's output reports both failures, not only the first one encountered

### Requirement: Every skill is registered, and every skill is CI-covered

A CI step SHALL assert, for every `skills/*/` directory: (a) it is registered in
`skills/marketplace.yaml`, and (b) it either has a dedicated job in `skills-ci.yml` or is
named in a documented `EXEMPT` mapping. Both directions SHALL be checked — a skill directory
existing without a registry entry, and a registry entry existing without a corresponding
directory being neither sufficient nor previously verified by any existing check.

#### Scenario: An unregistered skill directory fails CI

- **WHEN** a skill directory exists under `skills/` with no entry in `skills/marketplace.yaml`
- **THEN** the `all-skills` job fails, naming the directory and the missing registration

#### Scenario: A registered skill with neither a job nor a documented exemption fails CI

- **WHEN** a skill directory is registered in `marketplace.yaml` but has no dedicated job in
  `skills-ci.yml` and no entry in the `EXEMPT` mapping
- **THEN** the `all-skills` job fails, naming the directory and pointing at ADR 0030 for how
  to add a job or a documented exemption

### Requirement: A documented CI exemption stays true or fails loudly

Skills exempted from a dedicated job (the template's "Subjective skills" class,
`docs/SKILL_TEMPLATE.md` §5.B) SHALL have their exemption re-checked against the same signal
that justifies it — the absence of `evals/evals.json` — on every CI run. An exemption SHALL
NOT be able to silently outlive the condition that justified it.

#### Scenario: An exempted skill that gains real evals fails its exemption check

- **WHEN** a skill named in the `EXEMPT` mapping gains an `evals/evals.json` file
- **THEN** the `all-skills` job fails, naming the skill and stating that its exemption is
  stale, rather than continuing to treat it as exempt

#### Scenario: An exempted skill without evals passes cleanly

- **WHEN** a skill named in the `EXEMPT` mapping has no `evals/evals.json` file
- **THEN** the `all-skills` job does not require it to have a dedicated lint/type/pytest job

### Requirement: The proof of this capability is coverage-measured, not merely smoke-tested

`scripts/validations/F_050.py` SHALL be imported and exercised by the offline pytest suite
(`tests/test_validation_scripts.py`) and counted in the quality-gate tooling coverage step
(`quality-gates.yml`'s `--cov=` list), not only invoked by `scripts/validate.py --tier fast`
as a subprocess smoke check.

#### Scenario: F_050 regresses under a `.github/`-only PR

- **WHEN** a PR modifies only `.github/workflows/skills-ci.yml` in a way that breaks one of
  `F_050.py`'s assertions
- **THEN** the offline pytest suite that `eval-harness-ci.yml` runs on that PR fails, because
  `F_050` is part of `tests/test_validation_scripts.py`'s parametrized suite — not only
  `quality-gates.yml`'s path-filtered job, which may not fire on a `.github/`-only change
