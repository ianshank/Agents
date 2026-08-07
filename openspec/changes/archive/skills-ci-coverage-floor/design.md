# Design: skills-ci-coverage-floor

Promotes to [ADR 0030](../../../../docs/decisions/0030-skill-ci-tiers.md). Format follows the
house ADR idiom (Context / Decision / Consequences) — see the ADR for the full rationale,
including the relationship to ADR 0021 (CI gate delegation) and the alternatives considered.
This file adds the `openspec-quality-plan` mandatory section and the design points specific
to the implementation (not repeated in the ADR).

## Context

See `./proposal.md` §Why and ADR 0030 §Context for the measured gap: 4 of 11 registered
skills ran no CI on their own changes, including the drift guard that catches a vendored
`validate_skill.py` copy going out of sync with its canonical source.

## Decision

See ADR 0030 for the full decision and its rejected alternatives. Two implementation points
not covered there:

- **Accumulate, don't short-circuit.** Both the `all-skills` job's structural loop and this
  package's own local verification commands use the `rc=0; ...; cmd || rc=1; ...; exit $rc`
  idiom, not a bare `for` loop with no failure tracking (which would report success as long
  as the *last* skill in the glob passes, regardless of earlier failures) and not `|| exit 1`
  inside the loop (which would stop at the first failure and hide every failure after it).
- **`jsonschema` is installed explicitly in the new job.** `skill_marketplace.py`'s
  `validate_schema()` catches `ImportError` and only *warns* before returning — a lean
  install would silently no-op the registry schema check while the step still reported
  success. Confirmed live: `WARNING … jsonschema not installed; skipping schema validation`
  followed by `Skill marketplace OK ✓`, exit 0.

## Code Hygiene & Quality Gates

- **Tooling.** No new runtime dependency. `scripts/validations/F_050.py` is plain-stdlib and
  is linted/typed by the existing root `ruff`/`mypy` config (`pyproject.toml`) — it lives
  under `scripts/validations/`, not `skills/`, so no skill-local `ruff.toml` applies. The new
  `all-skills` workflow job needs only `pyyaml` (already a repo dependency) and `jsonschema`.
- **Coverage target.** `F_050.py` joins the existing `scripts/validations/` coverage floor
  (`quality-gates.yml`'s "Quality-gate tooling coverage (>=85%)" step) — not a new target. It
  is added to both `tests/test_validation_scripts.py`'s `parametrize` list and
  `quality-gates.yml`'s `--cov=` list. Without both, it would only be subprocess-smoke-tested
  by `scripts/validate.py --tier fast`: never coverage-measured, and never part of the
  offline pytest suite that `eval-harness-ci.yml` runs on `.github/`-only edits — the suite
  `test_validation_scripts.py` exists specifically because `F_031`/`F_037` broke silently on
  a `.github/`-only PR that `quality-gates.yml`'s path filter missed (PR #64). This change
  touches `.github/workflows/skills-ci.yml`, exactly the kind of edit that history warns
  about.
- **Configuration strategy — zero hard-coded values.** The `EXEMPT` mapping in the
  `all-skills` job follows the repo's own idiom for this (`docs.yml`'s
  `EXEMPT = {name: "reason"}` dict, not a bare set) rather than inventing a new one. Every
  declarative list this change introduces (`EXEMPT`, the F-050 `verification` bullets) is a
  named, commented, in-file constant — never a magic literal at a call site — per charter
  invariant §4.5.
- **Backwards compatibility.** Additive and fail-closed, no removal:
  - Existing green skill PRs stay green; the only behavior change is **more** CI running
    where less ran before (4 previously-uncovered skills go from 0 to ~8 job-minutes; see
    ADR 0030 §Context for the measured baseline).
  - **The one deliberate, decision-changing effect:** a skill directory added without a
    `marketplace.yaml` entry, or without either a dedicated job or an `EXEMPT` entry, now
    fails closed in `all-skills` — today it passes silently. That is the entire point of the
    change.
  - No `SCHEMA_VERSION`, registry alias, or existing F-ID's `validation_command` changes.

## Consequences

See ADR 0030 §Consequences. Locally to this package: `review.md` records the peer review
this design went through before implementation — the findings it raised (missing coverage
wiring, an internally-contradicted short-circuit rule, `ci_enforces` scoped too broadly, a
weaker classification for the subjective-skill exemption, an unresolved protected-path
question) are the reason the decision above reads the way it does, not a retrofit.
