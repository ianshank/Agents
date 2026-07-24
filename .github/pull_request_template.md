## Summary

<!-- What does this PR change, and why? Link the issue/ADR if there is one. -->

## Type of change

- [ ] Bug fix
- [ ] New feature (additive, opt-in)
- [ ] Documentation / repo organization
- [ ] Refactor / tech-debt
- [ ] CI / tooling

## Checklist

- [ ] `make check-all` passes locally (lint + type + tests at the package coverage floor).
- [ ] Added/updated tests for the change (offline & deterministic).
- [ ] Updated the relevant `CHANGELOG.md` (`[Unreleased]`/dev section, keep-a-changelog).
- [ ] If a component or import edge changed: updated `architecture.yaml` and regenerated `architecture.mmd`.
- [ ] If this is an architectural decision: added an ADR under `docs/decisions/` (see its README; do not backfill the intentional `0007` gap).
- [ ] Updated docs affected by this change (READMEs, `docs/`).

## Protected paths

- [ ] This PR **does not** touch protected evaluation paths (`features.yaml`, `config/**`, `src/eval_harness/{gating,scorers,judges}/`, `scripts/validations/**`, `tests/**`, `.github/**`); **or**
- [ ] It does, and I have requested the **`eval-change-approved`** label and CODEOWNER review. See [CONTRIBUTING.md](../CONTRIBUTING.md#protected-paths-require-a-labeled-approval).

## Notes for reviewers

<!-- Anything reviewers should focus on, risks, or follow-ups. -->
