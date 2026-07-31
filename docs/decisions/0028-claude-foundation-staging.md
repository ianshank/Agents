# 0028 — `claude-foundation` staging directory is the sanctioned interim state

- Status: **Accepted.**
- Date: 2026-07-31
- Related: [ADR 0017](0017-claude-foundation-reconciliation.md) (plugin for the generic
  layer, custom marketplace stays), `.github/workflows/claude-foundation-ci.yml`,
  `CHANGELOG.md` (M0–M6 staging entries, commit `c733fdf`), `NEXT_STEPS.md` (open M7
  extraction item).

## Context

A governance-drift audit (`docs/CHARTER_ALIGNMENT_AUDIT.md`) found that
[`docs/CHARTER.md`](../CHARTER.md) §3 and ADR 0017 both state `claude-foundation` is
consumed as a pinned plugin, "never vendored," and that "no code changes here until the
plugin's v1.0.0 exists" — while `claude-foundation/` is in fact a 55-file, fully
git-tracked, in-repo copy, added the same day as ADR 0017 (commit `c733fdf`).

Investigating turned up three independently-written artifacts, all dated the same commit,
that agree this is deliberate: `.github/workflows/claude-foundation-ci.yml` documents the
staging tree's own CI as "inert until extraction (ADR 0017)... delete this file in the
same PR that removes the `claude-foundation/` staging directory post-extraction";
`CHANGELOG.md` records "Execute `claude-foundation` M0–M6 (staged) — full plugin
implemented ... in the staging directory ... staging is CI-neutral here (per ADR 0017 the
plugin's final home is its own repo)"; and `NEXT_STEPS.md` still lists "Extract
`claude-foundation/` to its own repository" as the open M7 item. This is the signature of
an already-decided, already-executed plan tied to a peer-reviewed
`docs/plans/claude-foundation/PLAN.md`/`REVIEW.md` with M0–M7 milestones — not unnoticed
scope creep. The gap is purely wording: ADR 0017 and the charter describe the plugin's
*end-state* contract but never named the interim mechanism that produces it.

## Decision

1. **Building the plugin in-repo, in a self-contained staging directory, is the sanctioned
   way to reach ADR 0017's end state.** `claude-foundation/` is authored and CI-verified in
   this tree (M0–M6) so it can be built, tested, and reviewed before it has anywhere else
   to live — not vendored *from* an external source, but staged *toward* becoming one.
2. **The staging state is explicitly interim and self-terminating.** It ends when M7
   (`NEXT_STEPS.md`) extracts `claude-foundation/` to its own repository, tags a v1.0.0
   release, and this repo switches to consuming it as a pinned plugin per ADR 0017 §2 — at
   which point the staging directory and `claude-foundation-ci.yml` are deleted in the same
   PR (already documented in the workflow file's own header).
3. **Until extraction, the staging tree's CI stays isolated and non-blocking to the rest of
   the repo.** It does not gate `eval_harness`/`agent-core`/other packages' quality gates,
   and nothing outside `claude-foundation/` may import from it.
4. **ADR 0017 §2 ("never vendoring files into the repo") governs the end state, not this
   transition.** Once extraction happens, re-adding `claude-foundation/` as a full copy
   would be the vendoring ADR 0017 forbids; the staging period building it for the first
   time is not that.

## Consequences

- Closes the charter-alignment audit's finding without a scope change: the charter's
  claude-foundation scope bullet is reworded (this same PR) to name the staging exception
  and link here, rather than reading as flatly contradicted by `claude-foundation/`'s
  presence on disk.
- The self-termination condition is mechanically checkable going forward: M7 in
  `NEXT_STEPS.md` and the self-delete note in `claude-foundation-ci.yml` are the two
  places that must move together when extraction happens.
- No code, CI, or scope changes elsewhere in the repo. This ADR documents an already-taken
  path; it does not authorize anything new.
