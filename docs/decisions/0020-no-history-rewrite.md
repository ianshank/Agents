# ADR-0020 — No git-history rewrite for the rotated Langfuse keys

**Status:** accepted

**Context:**
A Langfuse secret/public key pair was committed early in the project's history to
three tracked files (`HARNESS_SPEC.md`, `docs/decisions/0003-langfuse-integration.md`,
`progress.md`). The keys have since been **rotated** — revoked in the Langfuse
dashboard, confirmed before this change merged — and the literals are scrubbed from the
working tree to a `<REDACTED — rotated, see incident record>` placeholder (F-038). The
pair still exists in remote git history, and the tempting follow-up is a history rewrite
(`git filter-repo` / BFG) to purge the keys from every historical commit.

**Decision:**
Do **not** rewrite history. Rotation is the mitigation; scrubbing the working tree plus a
fail-closed secret-scan gate (gitleaks, F-038) prevents reintroduction.

**Rationale:**
- The keys are already public in remote history — anyone who cloned before rotation has
  them. A rewrite removes nothing an attacker could not already have taken.
- A rewrite invalidates every existing clone, the open-PR bases (#16/#21) and the merged
  #30 lineage, every `implemented_in` provenance SHA in `features.yaml`, and the
  `merge-gate-data` branch's commit lineage (ADR 0018) — a large, high-blast-radius cost
  for zero real security gain.
- The local toolchain posture (TLS-blocked egress, fragile re-clone) makes a force-push
  rewrite operationally risky with no offsetting benefit.

**Consequences:**
- Historical commits retain the now-dead key strings, so the gitleaks **history** scan is
  report-only (`--exit-code 0`) while the **working-tree** scan (`--no-git`) is
  fail-closed. The single historical finding is known and expected.
- Any NEW secret introduced into the working tree fails CI via the fail-closed gate.
- `scripts/validations/F_038.py` guards that `.gitleaks.toml` exists, the workflow wires
  the fail-closed scan, and no key literal survives in the scrubbed files.

**Related features:** F-038.
