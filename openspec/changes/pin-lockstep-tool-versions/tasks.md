# Tasks: pin-lockstep-tool-versions

`[P]` = protected path → needs `eval-change-approved` + CODEOWNERS
(`scripts/eval_protected_paths.py`: `features.yaml`, `scripts/validations/**`,
`.github/**`). This package reads `.github/workflows/skills-ci.yml` from `F_055.py` but
never edits it, per `docs/plans/orbital-drift-alignment/PLAN.md` Phase 0 §1.

## 1. Source of truth (unprotected)

- [x] `scripts/tool_versions.py`: `RUFF_VERSION = "0.15.20"`, `MYPY_VERSION = "2.1.0"`
      (confirmed live in root `pyproject.toml:84` before writing, not assumed from the
      plan doc's numbers).
- [x] Module docstring explains the canonical-source role and points at
      `scripts/validations/F_055.py` as the enforcing script.
- [x] No logger — a plain constants module with zero runtime branching, matching the
      `scripts/eval_protected_paths.py` precedent (see `design.md` "Logging").

## 2. Lockstep proof `[P]`

- [x] `scripts/validations/F_055.py` — read-only (file reads only; no subprocess, no
      code execution, no writes), structured on `scripts/validations/F_031.py`'s shape
      (`_common.check`/`report`/`configure_logging`, same exit-code contract).
- [x] Regex `\b(ruff|mypy)==([^"'\s]+)` over raw file text, unanchored to a line so both
      the single-line and the one multi-line (`experiments/backend-validation`)
      `pyproject.toml` shapes are covered without a second code path.
- [x] Two checks per tool per file: presence (≥1 occurrence) and exact match on every
      occurrence found — not a hardcoded occurrence count (see `design.md`).
- [x] Covers all 7 `pyproject.toml` files plus `.github/workflows/skills-ci.yml`
      (read-only).

## 3. Docs (unprotected)

- [x] `AGENTS.md:97` pin bullet points at `scripts/tool_versions.py` and
      `scripts/validations/F_055.py` — one clause added, no restructuring.
- [x] `docs/decisions/0034-tool-version-lockstep.md` + index row in
      `docs/decisions/README.md`.
- [x] `CHANGELOG.md` entry under `[1.3.0-dev]`.

## 4. OpenSpec package (this package)

- [x] `proposal.md`, `design.md`, `tasks.md`, `specs/tool-version-lockstep/spec.md`.
- [x] Add this change to the "Current changes" list in `openspec/README.md` — mechanically
      required, or the *OpenSpec change index* guard in `.github/workflows/docs.yml`
      fails CI (`openspec/README.md:27-30`).
- **Gate:** every file this package links to resolves (no dangling reference).

## 5. Governance `[P]`

- [x] `features.yaml`: F-055 claimed, `category: infrastructure`, `tier: fast`, one
      `verification` bullet per checked invariant.
- [x] Ledger lands `status: in_progress` alongside `F_055.py` in one commit, then flips
      to `status: done` with `implemented_in` set to *that* commit's SHA in a second,
      small commit — the `ae1cfc6` derivation rule this repo already uses (verified
      against the F-053 precedent: `git show bc0ae2c` / `git show f1f73a3`), which
      resolves the self-reference problem (a commit cannot contain its own hash)
      without a placeholder value.

## 6. Verification

- [x] `python scripts/validations/F_055.py` — clean pass against the already-in-sync
      tree (see report for pasted output).
- [x] Deliberate mismatch: `agent-core/pyproject.toml`'s `ruff==0.15.20` edited to
      `ruff==0.14.0`, re-run reproduces a targeted failure naming the file and both
      versions, then reverted (`git diff` empty afterward — see report for pasted
      output).
- [x] `python scripts/validate.py --tier fast` green after the `status: done` flip,
      confirming the harness discovers and runs `F_055.py` via `features.yaml` rather
      than only via a standalone invocation.

## Archive

- [ ] This change stays listed under `openspec/README.md`'s "Current changes" (not moved
      to `changes/archive/`) even though F-055 lands `status: done` in the same PR —
      matching current house practice for other done-status F-IDs whose OpenSpec package
      has not yet been through `openspec archive` (e.g. `add-eval-matrix-completeness` /
      F-053, still listed as "proposed" in `openspec/README.md` despite
      `features.yaml`'s F-053 row reading `status: done`). Archiving is a separate,
      later step, not part of this change.
