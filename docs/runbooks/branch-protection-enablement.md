# Runbook: enable branch protection on `main` (ADR 0037)

This is an **admin settings change**. An agent session cannot perform it and must
not claim that it has. The repository ships an advisory checker so the candidate
required-check set is derived from files, not restated from memory.

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
python scripts/check_branch_protection.py --probe --repository OWNER/REPO
```

The names come from `.github/workflows/required-check-stubs.yml` (the ADR 0040
stub/real pairing). `--strict` exits 1 when protection is absent or a derived
check is missing; default exit is 0 so CI stays advisory.

Also require `secret scan (gitleaks)` if you require checks at all: that workflow
is unfiltered and **must not** be stubbed (a stub would be a false green). It
will show as `extra` relative to the stub-derived set — that is expected.

## GitHub UI steps (human)

1. Settings → Branches → Add classic branch protection rule for `main`.
2. Enable **Require status checks to pass before merging**.
3. Add every context printed by `check_branch_protection.py`, plus the unfiltered
   secret scan after it has soaked green.
4. Do **not** enable **Require review from Code Owners**.
5. Leave `merge-gate-data` **unprotected** (ADR 0018 store-sync pushes there).
6. Record the admin-bypass posture ("Do not allow bypassing the above settings")
   in the PR or issue that documents the settings change. ADR 0037 does not
   mandate a direction; it forbids leaving the choice implicit.

## Unblock for Code-Owner review

Once a second collaborator with commit access exists, revisit ADR 0037. Until
then `.github/CODEOWNERS` documents intent only.
