---
name: pre-pr-gate
description: Run every quality/regression/architecture gate this repo's CI enforces, chained locally as one command, before opening or updating a PR. Use this whenever the user asks whether a branch is ready to merge, wants the full test suite run before pushing, needs a branch validated end to end, or mentions a "pre-PR checklist" or "run everything before I push".
validator_version: '2.0'
compatibility: python>=3.10, GNU make
version: 1.0.0
---

# pre-pr-gate — E2E Action Skill

Run this repo's complete pre-PR validation battery — every gate `quality-gates.yml`
and `architecture-drift.yml` enforce in CI, plus the advisory checks this repo has
but previously left scattered across `AGENTS.md` prose and CI YAML — as one command,
and report a single pass/fail with evidence.

## 1. Preconditions (input contract)

- A checkout of this monorepo with `make` on `PATH` and the dev extras installed
  (`make install` / `make install-all`).
- The working tree state to validate is already the checked-out state — this skill
  does not stash, commit, or switch branches.
- The local base ref (`main` by default) should be up to date with its remote. A
  stale local ref produces misleading `regression_gate.py`/`repo-invariant-review`
  findings that point at already-merged, unrelated commits rather than the branch
  under review — `git fetch origin main:main` first if in doubt; this gate does not
  do that for you.

## 2. Procedure (the E2E steps)

1. From the repo root, run `make pre-pr`, or equivalently
   `python skills/pre-pr-gate/scripts/run_pre_pr_gate.py --root .` — the same thing
   via a script, so the result is a checkable artifact rather than only terminal
   output. Pass `--base-ref <ref>` (or `PRE_PR_BASE_REF=<ref>` to `make` directly) to
   compare against something other than `origin/main`.
2. The chain, in order: `make check-all` (root + all 5 sibling packages' own quality
   gates), `make invariants` (charter invariants + charter drift),
   `check_size_budget.py`, `check_guard_reachability.py`,
   `check_skill_script_drift.py`, `check_protected_changes.py`,
   `regression_gate.py --base-ref <ref>`, `validate.py --tier fast --strict-git`,
   `architecture-drift-guard`'s `drift_check.py` and `mermaid_gen.py --check`,
   `skill_marketplace.py validate`, `make determinism`, and finally
   `repo-invariant-review`'s `check_invariants.py` (advisory — see its own SKILL.md
   for why it stays non-blocking here: several of its checks already duplicate gates
   earlier in this same chain).
3. `make pre-pr` accumulates every failure instead of stopping at the first, so read
   the **whole** output — fixing one and re-running can hide the next one behind it.
4. A clean exit means the branch is safe to push from a **local validation**
   standpoint. Real CI still runs independently and can differ under
   network-dependent or environment-specific conditions this gate cannot see
   locally (e.g. secret-scanning, GitHub-hosted-runner specifics).

## 3. Output contract (postconditions — what "done" means)

- `make pre-pr` (equivalently `run_pre_pr_gate.py`) exited 0, **or** every failure it
  reported has been fixed and it was re-run to a clean exit.
- When `--out <path>` is passed to `run_pre_pr_gate.py`, `<path>` is valid JSON:
  `{"passed": bool, "exit_code": int, "target": str, "root": str}`.

## 4. Failure handling

- **Report with evidence.** Relay the actual failing check names from the output —
  each step in the chain prints its own `[pre-pr] ...` label — not a bare "something
  failed".
- **Never skip, disable, or work around a failing check to force a pass.** A check
  red here would also be red in real CI; fix the underlying cause.
- **Idempotent.** Re-running is always safe — every chained step is itself read-only
  or self-cleaning; no state is left behind for a next run to trip over.

## 5. Validation gate (before declaring success)

Artifact-producing skill — not done until this exits 0:

```bash
python scripts/validate_skill.py --skill . --tier structural,behavioral
```

## 6. Examples

**Example 1**
Input: "Is this branch ready to open a PR?"
Output: runs `make pre-pr`; reports each chained check's pass/fail and an overall
verdict, with a fix-and-rerun loop if anything failed.

**Example 2 (edge case)**
Input: `--root` points at a directory with no `Makefile` at all (e.g. a
misconfigured fixture, or a script run from the wrong working directory).
Output: fails closed — a non-zero exit surfacing `make`'s own "no makefile found"
error — rather than silently reporting success.

---

## Bundled layout

```
pre-pr-gate/
├── SKILL.md
├── scripts/
│   ├── run_pre_pr_gate.py   # thin wrapper around `make <target>`; the check list
│   │                        # itself lives in the Makefile, not duplicated here
│   └── validate_skill.py    # vendored copy of skills/common/skill_validator.py
├── tests/
│   └── test_run_pre_pr_gate.py
└── evals/
    ├── evals.json
    └── fixtures/
        ├── passing/Makefile
        ├── failing/Makefile
        └── no-makefile/      # deliberately empty — tests the fails-closed path
```
