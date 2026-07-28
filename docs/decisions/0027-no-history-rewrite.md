# ADR-0027 — No git-history rewrite for the leaked Langfuse keys

**Status:** accepted

**Context:**
A Langfuse secret/public key pair was committed early in the project's history to three tracked
files (`HARNESS_SPEC.md`, `docs/decisions/0003-langfuse-integration.md`, `progress.md`), and
survived there until this change scrubbed the working tree to a
`<REDACTED — rotated, see incident record>` placeholder. The pair still exists in remote git
history, and the tempting follow-up is a history rewrite (`git filter-repo` / BFG) to purge the
keys from every historical commit.

**Rotation status is a separate, human-owned step and is NOT asserted here.** An earlier draft
of this decision (on the unmerged `feat/F-038-gitleaks` branch) stated the keys were "revoked
in the Langfuse dashboard, confirmed before this change merged." That branch never merged, the
literals remained in `main` for another three weeks, and no written confirmation exists. This
ADR therefore records the rewrite decision only. `NEXT_STEPS.md` separately checks off rotating
the keys in the dashboard and in `.env` files; that item is about the dashboard action, not the
document scrub, and it is not evidence the rotation was verified.

**Decision:**
Do **not** rewrite history. Scrubbing the working tree plus a fail-closed secret-scan gate
prevents reintroduction; rotation — once confirmed — is the actual mitigation for the exposure
that already happened.

**Rationale:**
- The keys are already public in remote history. Anyone who cloned before now has them, so a
  rewrite removes nothing an attacker could not already have taken.
- A rewrite invalidates every existing clone, every open pull-request base, every
  `implemented_in` provenance SHA in `features.yaml`, and the `merge-gate-data` branch's commit
  lineage (ADR 0018) — a large blast radius for zero real security gain.
- This repository has **no branch protection** on `main`, so nothing here may claim protection
  rules as a mitigating or complicating factor in either direction.

**Consequences:**
- Historical commits retain the dead key strings, so the gitleaks **history** scan is
  report-only while the **working-tree** scan (`--no-git`) is fail-closed. The single
  historical finding is known and expected.
- Any NEW secret introduced into the working tree fails CI via the fail-closed gate.
- A validation script guards that `.gitleaks.toml` exists, that the workflow wires the
  fail-closed scan, and that no key literal survives in the scrubbed files.
- Exposure remains until rotation is confirmed in writing. That is tracked as a human checklist
  item and blocks the public-facing work in
  `openspec/changes/add-measurement-harness-wedge/`, not this ADR.

**Related features:** F-ID claimed at land (see `features.yaml`).
