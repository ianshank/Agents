# Peer Review — `skills-ci-coverage-floor` plan (2026-07-31)

**Reviewed artifact:** the implementation plan drafted for this change, before any file was
touched.
**Method:** critiqued against the quality bar `openspec-quality-plan/SKILL.md` sets for this
exact artifact type, cross-checked against `docs/SKILL_TEMPLATE.md`,
`tests/test_validation_scripts.py`, `scripts/eval_protected_paths.py`, and the
`docs.yml` component-README guard the plan cites as precedent. Every claim below was verified
against the repo at `4d30636`, not asserted from memory.
**Outcome:** eight findings, all resolved before implementation began. None required
reopening a decision the user had already made (full OpenSpec ceremony; the three evals-less
skills as a permanent, template-grounded class) — all were plan-quality and internal-
consistency defects.

---

## Findings

**1. [High, RESOLVED] Missing mandatory "Code Hygiene & Quality Gates" section.**
`openspec-quality-plan/SKILL.md` requires `design.md` to explicitly name tooling, coverage
targets, configuration strategy, and backwards-compatibility approach, and requires every
`tasks.md` phase to close on a hygiene/test gate. The draft plan had neither. *Resolution:*
`./design.md` now carries the mandatory section verbatim; `./tasks.md` closes every phase on
a concrete gate command.

**2. [High, RESOLVED] New proof script never wired into the coverage-measured offline
suite.** `tests/test_validation_scripts.py` hard-codes an explicit `parametrize` list of
F-modules that the offline pytest suite imports and runs; `quality-gates.yml` hard-codes a
matching `--cov=` list. The draft never added the new F-module to either — meaning it would
only be subprocess-smoke-tested by `scripts/validate.py --tier fast`, never coverage-measured,
and never part of the suite that `eval-harness-ci.yml` runs on `.github/`-only edits. That
suite exists *because* F-031/F-037 broke silently on a `.github/`-only PR that
`quality-gates.yml`'s path filter missed (PR #64) — the exact failure class this change
addresses. *Resolution:* F-050 is wired into both lists; verified locally (`pytest
tests/test_validation_scripts.py` and the full quality-gate coverage step both green with
F_050 included).

**3. [Medium, RESOLVED] Stated principle contradicted by its own verification snippet.**
The draft's `all-skills` job description said "accumulate failures, never short-circuit" but
its own local-verification command block used a bare `for` loop with no accumulator — which
reports success as long as the *last* skill in the glob passes, regardless of earlier
failures. *Resolution:* both the job and the verification commands use the same `rc=0; ... ||
rc=1; ... exit $rc` idiom, defined once.

**4. [Medium, RESOLVED] `ci_enforces` prescribed for assertions it wasn't built for.**
`_common.ci_enforces` exists to handle delegation ambiguity (a step might run inline or
through the ADR-0021 `quality-gate.sh` chain). The draft said every "CI runs X" assertion
should go through it — but the new `all-skills` job's own commands are, by design, never
delegated (see ADR 0030, "Relationship to ADR 0021"), so forcing `ci_enforces` onto them means
passing a meaningless `gate` argument. *Resolution:* `F_050.py` asserts the new job's commands
via plain substring checks, matching how `F_037.py`/`F_045.py` already treat `skills-ci.yml`
content that has no delegated form.

**5. [Medium, RESOLVED] "Third class" reinvented a category the repo already names.**
`docs/SKILL_TEMPLATE.md` §5 branch B, "Subjective skills," is this exact category
("structural only… self-check against explicit criteria… can omit `evals/` entirely"), and
`openspec-quality-plan/SKILL.md` and `openspec-peer-review/SKILL.md` both open their own §5
with "**Subjective skill validation:** There is no honest scripted gate…". *Resolution:* ADR
0030 cites these directly and adopts "subjective skill," converting the ADR from inventing a
classification to codifying one the skills already claim about themselves.

**6. [Low, RESOLVED] Unresolved rhetorical hedge in a handoff artifact.** The draft's ADR
workstream header read `[P for the index? no — docs/ is unprotected]` — a visible unresolved
question. Verified directly against the full `PROTECTED_PATTERNS` tuple: `docs/**` is
confirmed absent. *Resolution:* cleaned to a plain, verified statement, applied consistently
to the (also unprotected) OpenSpec-package workstream too.

**7. [Low, RESOLVED] The guard being built had the same staleness risk it exists to close.**
The `EXEMPT` set had no check that an exemption stays true over time — if a listed skill later
grew `evals/evals.json` and real library code, it would keep silently skipping the
dedicated-job requirement forever. *Resolution:* the guard re-checks every `EXEMPT` entry
against `evals/evals.json` at runtime and fails if it's gone stale; verified live (adding
`evals/evals.json` to an exempted skill's directory fails the guard with a message pointing at
ADR 0030).

**8. [Low, RESOLVED] No explicit compatibility/impact statement.** The draft never stated, in
one place, what observably changes for a contributor. *Resolution:* both `design.md`'s
Code Hygiene section and `proposal.md`'s Impact section now name it directly: a skill added
without registration or a job now fails closed where it previously passed silently.

## Verification performed during review

- Extracted and executed the `all-skills` job's embedded registration/coverage-guard Python
  directly (dedented per YAML block-scalar rules) against the live repo: passes clean (11/11
  skills registered and covered).
- Mutation 1: an unregistered, job-less `skills/_tmp/` directory fails both check arms.
- Mutation 2: adding `evals/evals.json` to an `EXEMPT` skill fails the staleness check.
- `docs/SKILL_TEMPLATE.md` read in full to confirm §5 branch B exists as described (not
  inferred from the section's opening lines alone).
- `scripts/eval_protected_paths.py`'s full `PROTECTED_PATTERNS` tuple read to confirm `docs/**`
  and `openspec/changes/**` are both absent.
