# Design: add-foundation-reviewer-charters

## Placement

| Concern | Home | Why |
|---|---|---|
| `spec-guardian` / `peer-reviewer` charters | `claude-foundation/agents/` | Mirrors `explorer.md`/`test-runner.md` exactly: frontmatter schema-validated by `foundation_tools.validate`'s `check_agents()`, surface-tracked by `foundation_tools.backwards_compat` |
| Fleet lifecycle mapping | `openspec/AGENTS.md` | Existing "native roles" table; the only place this repo names which sub-agent owns which OpenSpec phase |
| Registration | `claude-foundation/README.md`, `CHANGELOG.md`, `tests/backwards_compat_baseline.json` | `claude-foundation/CLAUDE.md`'s own documented agent-registration convention — reused unchanged |

No `architecture.yaml` edit, no new import edge, no engine change: this is a plugin
registration, exactly like adding a third skill would be, not a new component kind.

## Why portability is the central design problem

This is the least obvious part of the change, so it gets stated plainly: **a charter that
lives in `claude-foundation/` is not being written for this repo.** `claude-foundation`'s own
README calls itself "the single-source-of-truth alternative to copy-pasting agent config
across repos," ships components that "carry no hardcoded values (all configuration is via
environment variables)," and is consumed by name-checked "Consumer Repos" in its own C4
diagram (`docs/architecture.md`: "Agents, MouseDroid-AGI, piodeer, SQE platform"). `explorer.md`
and `test-runner.md` already honor this — neither references `openspec/`, `features.yaml`,
`docs/decisions/`, or any other path specific to this monorepo, and `foundation_tools.scan`
mechanically enforces the adjacent no-hardcoded-values policy (full model IDs, absolute
paths, credentials) on every file under `claude-foundation/agents/`.

A spec-conformance reviewer is unusually tempted to violate this. Its entire job is "does the
implementation match the plan/spec/decisions" — and in *this* repo, that surface has a name:
`openspec/`, `docs/decisions/` ADRs, `features.yaml` F-IDs. Writing those paths directly into
`spec-guardian.md` would make it work here and nowhere else — the same mistake ADR 0028 warns
against in the opposite direction (vendoring "toward" a repo instead of staying repo-agnostic
"from" one), and a direct violation of the portability property this change is explicitly
required to preserve (`docs/plans/orbital-drift-alignment/PLAN.md` Phase 4: "zero
repo-specific paths ... matches `explorer.md`/`test-runner.md`").

## The resolution: an algorithm, not a target

Both charters' `## Rules` specify a **discovery procedure** — an ordered list of *candidate*
conventions to check for existence at invocation time — never a filesystem path assumed to
exist. The order, taken verbatim from `docs/plans/orbital-drift-alignment/PLAN.md` Phase 4:

1. `CLAUDE.md` — the most common "read this first" convention for a Claude Code repo.
2. `AGENTS.md` — a competing/complementary convention; some repos ship both.
3. `openspec/` — the spec-driven-change front-end this repo uses (this repo's own
   `openspec/README.md` calls it "a thin coordination/authoring front-end ... fully
   removable" — so even *this* repo cannot be assumed to keep it, and the charter must not
   assume it either).
4. `docs/decisions/` — an ADR directory, this repo's own (33 entries as of this change).
5. `specs/` — a bare, tool-agnostic specs directory some repos use without a wrapper.
6. `.specify/` — the directory convention used by GitHub's `spec-kit` tool, a real
   alternative this repo itself evaluated and declined (`openspec/project.md`: "A
   SpecKit-vs-OpenSpec bake-off was previously evaluated and dropped").

The rule is explicit that this is a check, not an assumption: "use whichever actually exist;
if none exist, say so explicitly rather than failing silently or inventing a convention."
That third branch — *nothing found* — is deliberate and required, not an edge case bolted on
afterward: a conformance reviewer that invents a convention when it finds none is worse than
one that admits it found nothing, for the same reason a panel that averages disagreement into
a confident number is worse than one that abstains (`add-panel-judge/design.md`, "Aggregation
and abstention").

**This repo is not a special case of its own algorithm.** Run the discovery order against
*this* worktree today: `CLAUDE.md` does not exist at the repository root (only
`claude-foundation/CLAUDE.md` does — out of scope for a root-level check); `AGENTS.md` exists,
twice, at different depths (`/AGENTS.md` and `/openspec/AGENTS.md`); `openspec/` exists;
`docs/decisions/` exists. A charter run here would correctly proceed with `AGENTS.md` +
`openspec/` + `docs/decisions/` and correctly skip the absent `CLAUDE.md` — exactly the
"whichever actually exist" behavior the rule specifies, verified by hand rather than assumed
(`ls` at repo root, `find . -maxdepth 2 -iname AGENTS.md`, both run while authoring this
package).

## What the charters do NOT do

Neither charter has Bash, so neither can run `git diff` itself to *find* a change's touched
files. This is intentional, not a gap: both mirror `foundation:code-review`'s existing
contract ("Identify the review target: the provided diff, the named files, or ... the files
the caller describes") — the caller (a human, a skill, or Phase 5's future dispatcher) names
the target; the charter's job starts at reading it, not at discovering it via shell. The
discovery procedure above is about *conventions* (what counts as "the spec/plan/decision
surface" in this repo), not about *locating the diff*, which stays the caller's
responsibility exactly as it already is for `code-review`.

## Two charters, not one

A single combined charter was considered and rejected. `spec-guardian` and `peer-reviewer`
answer different questions under different failure modes:

- `spec-guardian` asks "does this still match what it says it does" — a conformance check
  against the change's *own* declared surface. It can be wrong by missing drift; it cannot be
  wrong by inventing a requirement that was never declared, because it only compares against
  what the change itself claims.
- `peer-reviewer` asks "is what it declared actually correct, and does it survive an attack"
  — it fact-checks the declarations themselves and then tries to break them. It can be wrong
  by missing an attack; it is explicitly required not to be wrong by asserting an unverified
  one (Rule 5 in both charters: never record a claim or attack not personally verified).

Collapsing these into one charter would blur "the plan is internally consistent" with "the
plan is correct," the same distinction `add-panel-judge/review.md`'s own two-pass structure
draws between its first pass (mechanical fact-check) and second pass (adversarial attack) —
this change's `peer-reviewer` *is* that method, generalized into a reusable charter instead of
re-derived by hand each time. Sequencing them (`spec-guardian` first, gating a `peer-reviewer`
dispatch) is a Phase 5 concern (the dispatcher skill), not encoded in either charter itself —
each charter is independently invocable and neither hardcodes the other as a precondition.

## Model and turn-budget choices

Neither existing agent's model choice transfers directly: `explorer` is `haiku` because
breadth (cheap fan-out search) is the thing being bought; `test-runner` is `inherit` because
mechanical command execution should track whatever model the calling session already trusts.
Both new charters are buying *judgment* — comparing prose claims to code, then trying to break
them — so a fixed, capable alias fits better than either precedent:

- `spec-guardian`: `sonnet` — a conformance check is bounded and single-pass; a mid-tier
  model with real reasoning is enough to compare a declared surface against current files
  without the cost of the top-tier alias.
- `peer-reviewer`: `opus` — the adversarial pass explicitly rewards catching what a lighter
  pass would miss (see `add-panel-judge/review.md`'s second pass, which found four further
  corrections a first pass missed); this is the one place in the fleet where the strongest
  available reasoning is the point of the dispatch.

`maxTurns` reuses this repo's only two precedent values instead of inventing a third:
`spec-guardian` (30, matching `explorer` — a bounded read/search/compare procedure) and
`peer-reviewer` (40, matching `test-runner` — a longer, multi-step procedure, here two
passes instead of an iterate-to-green loop).

## Verdict vocabulary

`foundation:code-review` (the one existing review surface in this plugin) ends every run with
"exactly one verdict line": `Verdict: blocking` / `Verdict: non-blocking` / `Verdict: clean`.
That convention is reused structurally — one verdict line, first, lowercase state word — but
not its vocabulary: `code-review`'s states are severity tiers over defects, while
`spec-guardian` measures a different axis (does the implementation match what it claims to
do). Reusing "blocking/clean" wording for a conformance check would misleadingly imply the
same severity scale. `spec-guardian` instead reports `Verdict: conforms` / `Verdict: drift` —
the repo's one-line-verdict *shape*, a vocabulary specific to what is actually being measured.
`peer-reviewer` follows `review.md`'s own established shape instead (a `## Verdict`-equivalent
prose summary, not a single enum word), because that is the real, in-repo artifact its output
is meant to produce — see `openspec/changes/add-panel-judge/review.md`'s own `## Verdict`
section for the precedent being matched.

## Dogfood and worktree isolation

Decision Point 1 substitutes "structural validation + dogfooding on a real change" for a
scripted eval suite. The intended dogfood target is Phase 1's
(`harden-quality-gate-integrity`) merged diff, producing
`openspec/changes/harden-quality-gate-integrity/review.md`.

This package was authored in an isolated git worktree branched from
`docs/plans/orbital-drift-alignment/PLAN.md`'s base commit, parallel to (not sequenced after)
Phase 1's own worktree. Checked directly rather than assumed: `git log --all --oneline` in
this worktree surfaces no commit touching
`skills/quality-gate/scripts/gategen/render.py`'s `_ignored_override_notice` or a
`PYTEST_ADDOPTS` guard (Phase 1's stated changes), and `git worktree list` shows no
`harden-quality-gate-integrity`-titled worktree — only this change's own worktree and
sibling worktrees on unrelated branches. Git worktrees share one object database but not each
other's uncommitted working trees or unmerged branches; Phase 1's actual diff is not reachable
from here by construction, not by an oversight this package could route around.

The dogfood step is therefore reported as **blocked**, not skipped silently and not
fabricated. `openspec/changes/harden-quality-gate-integrity/review.md` is not created by this
package. `tasks.md` §4 records the blocker and the exact commands run to confirm it. The
orchestrating session — which will have both this change's charters and Phase 1's landed diff
in the same tree — is the correct place to run the real dogfood pass
(`docs/plans/orbital-drift-alignment/PLAN.md`, Verification section, names this explicitly as
part of the plan's overall acceptance, not this worktree's).
