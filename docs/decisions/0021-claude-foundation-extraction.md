# ADR-0021 — claude-foundation extraction to its own repository

**Status:** proposed

**Context:**
The generic Claude Code plugin lives as a staging directory `claude-foundation/` in this
monorepo (M0–M6 complete: 4 skills, 2 subagents, 3 hooks, `foundation_tools` at 94% coverage,
CI inert inside the monorepo). Per ADR 0017 its final home is its own repository, consumed here
by a pinned plugin install — never vendored. Extraction readiness is verified on the current
`main`: ruff + format clean, `mypy tools`/`mypy hooks` (strict) clean, `pytest` 102 passed /
94.8% coverage (gate 85), and `claude plugin validate` green.

**Decision:**
1. **Fresh import, not `git filter-repo`.** The staging tree is copied into a new
   `ianshank/claude-foundation` repository; the first commit records provenance (the agents SHA it
   was extracted from). Consistent with ADR 0020 (no history rewrite) and the local
   TLS-blocked / fragile-clone posture — a filtered-history subset buys nothing here and adds risk.
2. **v1.0.0 pin.** The new repo activates its currently-inert `ci.yml`, enables branch protection
   from day one, and tags `v1.0.0` (matching `plugin.json`). Agents consumes the plugin pinned to
   that tag.
3. **Single revert point.** The staging directory `claude-foundation/` and its root orchestration
   workflow `.github/workflows/claude-foundation-ci.yml` are deleted **together in one PR** (they
   "exist or vanish together", F-037), keeping the removal cleanly revertible.
4. **Config-only dogfood (ADR 0017).** In this repo, M7 is marketplace-add + plugin-install only —
   no Python, no workflow-job changes, no edits under `skills/`. The four domain skills
   (`openai-judge`, `architecture-drift-guard`, `eval-corpus-forge`, `model-bench`) stay untouched;
   the generic layer comes from the pinned plugin.

**Consequences:**
- `scripts/validations/F_039.py` guards the post-extraction state: staging dir absent, pinned-plugin
  config present, the four domain skills still tracked (real directories, not symlinks, `SKILL.md`
  present), and no generic-skill duplicated into `skills/`.
- Until the new repo tags `v1.0.0`, the delete PR stays open; agents CI keeps running the staging
  suite via the root workflow, so nothing regresses in the interim.
- The outward, irreversible steps — repository creation, the `v1.0.0` tag, and merging the delete
  PR — are human-gated (G2–G4) and are not taken without explicit go-ahead.

**Related features:** F-039.
