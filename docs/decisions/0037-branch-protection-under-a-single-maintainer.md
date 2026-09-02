# 0037 - Branch protection under a single maintainer: required status checks, deferred Code-Owner review

**Status**: Proposed — this ADR records the decision and the settings to apply; the actual
GitHub branch-protection configuration is a repository-settings change made out-of-band by a
human with admin access, not by an agent, and is not itself part of any commit. See
`docs/plans/eval-evidence-integrity/PLAN.md` Phase 1 and its peer review at
`docs/plans/eval-evidence-integrity/REVIEW.md` (P1.4, Pass 2 A1).
**Date**: 2026-09-02

Related: [ADR 0005](0005-calibrated-merge-gate.md) (its enablement checklist item "Confirm
the regression gate and protected-path guard are *required* branch-protection checks" is
answered here), [ADR 0018](0018-outcome-store-persistence.md) (`merge-gate-data` must stay
unprotected), `scripts/eval_protected_paths.py` and `.github/CODEOWNERS` (the two-layer
eval-integrity design this ADR partially activates).

## Context and Problem Statement

Verified live against the GitHub API on 2026-09-02: `main` carries no branch protection at
all (`"protected": false`, and this holds for every branch in the repository). Every gate
this repository runs — the 96%/95%/85% coverage floors, the matrix and e2e-matrix freshness
checks, the charter invariant checks, the protected-path guard, all sixteen workflows — is
therefore advisory at the merge boundary. Nothing stops a push directly to `main`, and
nothing stops a pull request from merging with every check red.

`.github/CODEOWNERS` already maps all fifteen `PROTECTED_PATTERNS` entries to `@ianshank`,
mirroring `scripts/eval_protected_paths.py` exactly, as the repository's own comment states:
"GitHub CODEOWNERS provides the complementary, review-time enforcement; this script makes
the invariant mechanical in CI" (`scripts/check_protected_changes.py`). That complementary
layer depends on branch protection's "Require review from Code Owners" setting to have any
effect — CODEOWNERS entries do nothing on their own.

The repository has exactly one collaborator: `ianshank` (admin), confirmed via
`list_repository_collaborators`. GitHub does not allow a pull request author to approve their
own pull request. Enabling "Require review from Code Owners" on `main` while the sole
collaborator is also the sole CODEOWNER would therefore make every pull request in this
repository — including every agent-authored one — permanently unmergeable through the normal
review path. This is not a tuning question; it is a structural deadlock, and it is the
reason branch protection has never been enabled despite ADR 0005 naming it as a prerequisite
since 2026-06-30.

## Decision

1. **Enable required status checks on `main`, without a review requirement.** The candidate
   required-check set: the `quality-gates` workflow's `gates` and `eval-integrity` jobs, the
   `eval-harness-ci` test job, the four sibling-package CI workflows
   (`agent-core-ci`, `behavioral-regression-ci`, `flow-corpus-ci`, `claude-foundation-ci`),
   and `architecture-drift`. Before requiring any check, run it at least five times against
   `main` in its current state and confirm it is green every time — a flaky required check
   with one maintainer and no review-bypass path is a self-inflicted outage, not a safety
   improvement.
2. **Do not enable "Require review from Code Owners."** It is not merely unhelpful here, it
   is actively destructive under a single-collaborator repository. This ADR leaves it
   explicitly deferred, not silently absent — see the unblock condition below.
3. **Leave `merge-gate-data` unprotected.** `agent_core.store_sync push` writes directly to
   this branch as its designed persistence mechanism (ADR 0018); protecting it breaks that
   mechanism. This is a deliberate carve-out, not an oversight.
4. **Record the admin-bypass posture explicitly, whichever way it is set.** GitHub's "Do not
   allow bypassing the above settings" (i.e., include administrators) should be decided and
   stated in the actual settings change's accompanying record — this ADR does not mandate
   one direction, because the honest answer depends on operational judgment the repository
   owner is best placed to make, but it must not be left implicit. An unstated bypass posture
   makes every claim about "required" checks unverifiable from outside GitHub's own settings
   UI.
5. **`scripts/check_protected_changes.py --approved` remains available as an explicit, human
   invoked, logged override** — not a hole. Its docstring already frames it this way ("Force
   approve (explicit human override)"); this ADR does not change that script.
6. **Unblock condition for Code-Owner review**: once a second collaborator with commit access
   exists, revisit this ADR with a follow-up decision enabling "Require review from Code
   Owners." Until then, `.github/CODEOWNERS` continues to document reviewer intent for a
   future second maintainer without being mechanically enforced.

## Consequences

- **Positive.** Every coverage floor, freshness gate, and CI check this repository already
  runs becomes load-bearing rather than advisory the moment its required-status-check entry
  merges — this is the cheapest, safest way to close the enforcement gap identified in
  `docs/plans/eval-evidence-integrity/REVIEW.md` finding P1.4.
- **Positive.** ADR 0005's enablement checklist item "Confirm the regression gate and
  protected-path guard are *required* branch-protection checks" now has an executable path
  to closure, rather than an indefinitely unchecked box.
- **Negative.** The eval-integrity design remains one layer short: CI-mechanical enforcement
  (this ADR) exists, but human review-time enforcement (CODEOWNERS-backed Code-Owner review)
  does not, and cannot, until a second maintainer exists. Anyone reading only
  `.github/CODEOWNERS` without also reading this ADR could reasonably assume review is
  enforced when it is not.
- **Negative.** A maintainer with admin bypass enabled can still merge past a red required
  check. This ADR does not resolve that; it only asks that the choice be stated, not hidden.
- **Neutral.** No code changes ship with this ADR. The settings change it authorises happens
  in GitHub's repository settings, out-of-band, by a human with admin access — an agent
  session does not have the authority or the visibility to perform or verify it, and should
  not attempt to.

## Compliance

`scripts/check_guard_reachability.py` (or a sibling assertion, tracked as part of
`docs/plans/eval-evidence-integrity/PLAN.md` Phase 1) should eventually assert that every
protected pattern's guard job appears in the required-checks list, not merely that it fires
on the relevant `pull_request.paths` filter — today it proves only the latter. Until that
lands, compliance with this ADR is verified manually against GitHub's branch-protection
settings UI or `gh api repos/{owner}/{repo}/branches/main/protection`, not from repository
contents.
