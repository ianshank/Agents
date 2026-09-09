# Runbook: enable branch protection on `main` (ADR 0037)

This is an **admin settings change**. An agent session without repository-admin
credentials cannot perform it and must not claim that it has. **Agents must
not `--apply`.** Wait for five green runs of each candidate context against
`main` in its current state, then a maintainer with admin `gh` auth applies.
The repository ships a derived checker so the candidate required-check set is
never restated from memory.

Do **not** write `HUMAN_AUDIT` into the live store from an agent session.
Weekly labeling is `merge-gate-audit.yml` (queue) + `merge-gate-verdict.yml`
(human-triggered writer) only. Golden-corpus rows with `provenance=human`
are also human-only (`docs/golden-corpus/`).

## Why

Verified previously: `main` carries no branch protection. Every coverage floor and
CI workflow is advisory at the merge boundary. ADR 0037 authorises **required
status checks without Code-Owner review** until a second collaborator exists.

## Soak before requiring

A flaky required check with one maintainer and no review-bypass path is a
self-inflicted outage. Before requiring a context, run it at least five times
against `main` in its current state and confirm it is green every time.

## Candidate required-check set (derived)

Do not copy names from this paragraph into GitHub. Derive them:

```bash
python scripts/check_branch_protection.py
python scripts/check_branch_protection.py --emit-payload
python scripts/check_branch_protection.py --probe --repository OWNER/REPO
```

`--emit-payload` prints the classic-rule PUT body. Context names come from
`.github/workflows/required-check-stubs.yml` (the ADR 0040 stub/real pairing)
unioned with extra unfiltered workflows listed on
`BranchProtectionConfig.extra_required_workflows` (default: the secret-scan
workflow path). Override with repeatable `--extra-workflow PATH`. Job names are
rendered from those files; they are not string literals in the checker.
`--strict` exits 1 when protection is absent or a derived check is missing;
default exit is 0 so CI stays advisory.

An unfiltered secret-scan job is in the enablement set because that workflow
**must not** be stubbed (a stub would be a false green).

## Apply (admin `gh`)

`--apply` PUTs the derived payload. A 403/401 is **not enabled** (exit 1), not
success. This agent token cannot complete that call; a maintainer with admin
`gh` auth can:

```bash
python scripts/check_branch_protection.py --apply --repository OWNER/REPO
# optional: --enforce-admins  (GitHub: "Do not allow bypassing the above settings")
```

Default payload posture (single maintainer, recorded here so it is not implicit):

- Require a pull request with **zero** approving reviews (closes direct pushes
  without the CODEOWNERS deadlock).
- Do **not** require Code-Owner review.
- Do **not** require the branch to be up to date.
- Do **not** allow force pushes or deletions.
- **Admins may bypass** (`enforce_admins` false). Pass `--enforce-admins` to
  include administrators instead.

## GitHub UI steps (human, if not using `--apply`)

1. Settings → Branches → Add classic branch protection rule for `main`.
2. Enable **Require a pull request before merging** with 0 required approvals.
   Do **not** enable **Require review from Code Owners**.
3. Enable **Require status checks to pass before merging**. Add every `expected:`
   line from `check_branch_protection.py` (or import `--emit-payload`).
4. Leave `merge-gate-data` **unprotected** (ADR 0018 store-sync pushes there).
5. Record the admin-bypass posture in the PR or issue that documents the
   settings change.

## Unblock for Code-Owner review

Once a second collaborator with commit access exists, revisit ADR 0037. Until
then `.github/CODEOWNERS` documents intent only.
