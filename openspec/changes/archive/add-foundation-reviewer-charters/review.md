# Review: add-foundation-reviewer-charters

**Reviewed:** commit `9be04a8` (tip of `worktree-agent-a83ed32a5c4dec0db`, based on `7cdba73` on
`claude/orbital-drift-agents-reuse-aely36`; ancestry confirmed via `git merge-base --is-ancestor
7cdba73 HEAD`), independently, without reading the implementer's self-report first. Two passes,
dated separately — a mechanical fact-check of every falsifiable claim (verdicts CONFIRMED /
CORRECTED / REFUTED, each with evidence I generated myself, not pasted output) and an adversarial
design/behavioral review with attacks verified before being kept. Refuted attacks are recorded,
not deleted. House precedent and shape: `openspec/changes/add-panel-judge/review.md`.

## Verdict

The two charters are real, schema-valid, and genuinely portable. I ran `python -m
foundation_tools.validate`, `.scan`, `.backwards_compat`, `pytest --cov`, `ruff`, `mypy`, `claude
plugin validate .`, and `install_smoke.sh` myself in this tree — every one passes, and the
coverage run reproduces the claimed 96.03%/136-passed numbers exactly
(`claude-foundation/tests/`, live run below). The `backwards_compat_baseline.json` diff is
genuinely append-only — checked three ways (the commit's diff, the live file, and the parent
commit's copy) — and a byte-level dump confirms both `name:` fields match their filenames
exactly. Zero monorepo-specific paths leaked into either charter's `## Rules` section. The
implementer's flagged correction to `PLAN.md`'s Phase 4 table (the backwards-compat baseline is
a *protected* path, not unprotected as the table says) is independently confirmed true against
the actual scanner, CODEOWNERS, and CI path filter — and turns out to be even better-supported
than claimed, since `PLAN.md`'s own cross-cutting standards table already says "any package's
`tests/**`" is protected, one section above the Phase 4 table that contradicts it.

The one real, material gap is the dogfood proof `PLAN.md`'s own Phase 4 table requires
(dispatching both charters against Phase 1's merged diff to produce a functioning
`review.md`): it was not produced. I independently confirmed the implementer's blocker claim is
true, not an excuse — `git log --all` and `git branch -a` in this worktree show no commit or
branch for `harden-quality-gate-integrity` anywhere reachable. Unlike everything else in this
package, this gap is handled with real discipline: the task is left unchecked
(`tasks.md:68`), not silently dropped or falsely ticked, and both `design.md` and `proposal.md`
document the exact commands that establish the blocker. Beyond that, adversarial review found a
few smaller, real gaps — an unaddressed disagreement case between the two new charters, three
stale component-roster descriptions the registration checklist didn't cover, and a couple of
discovery-instruction asymmetries between the two charters — none of which are fabrications or
functional breaks, all suitable as follow-ups rather than reasons to hold the merge.

## Pass 1 — mechanical fact-check (2026-08-17, ~03:20-03:32 UTC)

Every command below was executed by me, in this worktree, just now — not copied from a report.

| # | Claim | Verdict | Evidence |
|---|---|---|---|
| 1 | Both charters pass `AgentFrontmatter` schema validation for real | **CONFIRMED** | `cd claude-foundation && PYTHONPATH=tools python3 -m foundation_tools.validate` → `check_agents` `findings: 0`, exit 0. Cross-checked with a direct `AgentFrontmatter.model_validate()` call on both files' parsed frontmatter — both construct cleanly. |
| 2 | `name:` byte-matches the filename stem exactly | **CONFIRMED** | `od -c` on both filename stems and both files' `name:` lines: `spec-guardian` / `spec-guardian.md:2`, `peer-reviewer` / `peer-reviewer.md:2` — identical byte sequences, no trailing whitespace, no case difference. |
| 3 | `model:` is a legal alias in both files | **CONFIRMED** | `spec-guardian.md:5` = `sonnet`, `peer-reviewer.md:5` = `opus`; both in `ALLOWED_MODEL_VALUES` (`schemas.py:22`, `{"haiku","sonnet","opus","fable","inherit"}`). |
| 4 | `## Rules` sections are generic/portable, no monorepo-specific path slipped in | **CONFIRMED** | Full read of both files plus a targeted `grep -niE` for a dozen monorepo-specific terms (`features.yaml`, `agent-core`, `behavioral-regression`, `flow-corpus`, `flow-protocol`, `eval_harness`, `orbital-drift`, absolute `/home/`/`Agents/` paths, `ianshank`, `F-NNN` feature IDs, `ADR 00`-prefixed numbers, `quality-gate.sh`) over both files — zero hits. `openspec/`/`docs/decisions/`/`specs/`/`.specify/` are named only as *candidates to check for existence*, not assumed paths — `design.md:14-70` makes the same argument at length and it holds up. |
| 5 | `python -m foundation_tools.scan` (no-hardcode scanner) is clean | **CONFIRMED** | Ran it: `{"files": 27, "findings": 0}`, `foundation-scan: OK`, exit 0. Scanner scope includes `agents/*.md` (`scan.py:33`), so this is a real check of the new files, not a no-op. |
| 6 | `pytest --cov` reproduces the claimed 96.03% / 136-passed | **CONFIRMED** | Ran the exact `quality-gate.sh coverage` invocation (`pytest --cov=foundation_tools --cov=hooks --cov-branch --cov-report=term-missing --cov-fail-under=85`): `136 passed`, `Total coverage: 96.03%`. Numbers match to the decimal. |
| 7 | `backwards_compat_baseline.json` diff is genuinely append-only | **CONFIRMED** | `git show 9be04a8 -- claude-foundation/tests/backwards_compat_baseline.json` adds exactly two lines (`"peer-reviewer"`, `"spec-guardian"`) to the sorted `agents` array; zero removals anywhere in the file; `recorded_major_version` is `1` in both the parent commit's copy (`git show 7cdba73:...`) and the current file — genuinely unchanged, not just claimed unchanged. Re-running `foundation_tools.backwards_compat` live now reports `added: {}, removed: {}` (baseline already reflects the live tree). |
| 8 | `ruff check .`, `ruff format --check .`, `mypy tools/hooks/tests` clean | **CONFIRMED** | All four ran clean: `All checks passed!`, `22 files already formatted`, `Success: no issues found` ×3. |
| 9 | `claude plugin validate .` passes | **CONFIRMED** | Ran it: `√ Validation passed`, exit 0. |
| 10 | `bash tests/smoke/install_smoke.sh` OK | **CONFIRMED** | Ran it: all four sub-checks (`claude plugin validate`, hook stdin contracts, validator, scanner) report OK, ends `install-smoke: OK`, exit 0. |
| 11 | `openspec/AGENTS.md`'s correction to "nothing here invents a new agent" is accurate | **CONFIRMED** | Two new `review` rows genuinely add `spec-guardian`/`peer-reviewer` as fleet owners (`openspec/AGENTS.md:21-22`) that did not exist before (`git show 7cdba73:openspec/AGENTS.md` has no `review` row at all) — the correction is not cosmetic, it tracks a real change. |
| 12 | Registration checklist items (README Components table, CHANGELOG `[Unreleased]`) are real, not fabricated | **CONFIRMED** | `claude-foundation/README.md:55-56` has two new `Subagent` rows matching the shipped charters' actual behavior; `CHANGELOG.md:19-31` has a matching `[Unreleased] > Added` entry. |
| 13 | Protected-path correction to `PLAN.md` Phase 4's table | **CONFIRMED** (full derivation in Pass 2, item (c)) | `scripts/eval_protected_paths.py:41`, `.github/CODEOWNERS:22`, `.github/workflows/quality-gates.yml:43`. |
| 14 | `openspec/README.md` "Current changes" entry is present and satisfies the actual CI gate | **CONFIRMED** | Entry present (`openspec/README.md:64-72`); I extracted and ran `docs.yml`'s own index-check Python inline against the live tree: `openspec index OK; 8 in flight, 4 archived`, exit 0. |
| 15 | Charter body shape: 1-2 sentence identity + exactly one `## Rules` heading + 5-6 numbered rules | **CONFIRMED** | Both open with a 2-sentence identity paragraph in the `explorer.md`/`test-runner.md` pattern ("You are a(n) X agent. Your job is to Y — never to Z."); `grep -n "^#"` shows exactly one `## Rules` heading in each; both have exactly 6 numbered rules. |
| 16 | Charter line count vs. Phase 0 §4's "~20-26 lines" template target | **CORRECTED** | `spec-guardian.md` is 27 lines, `peer-reviewer.md` is 28 — 1-2 lines over the stated approximate range (`explorer.md`=23, `test-runner.md`=25, both within range). Cosmetic; doesn't affect validation or portability. |
| 17 | `design.md:48`'s "`docs/decisions/` ... (33 entries as of this change)" | **CORRECTED** | Actual count is 32 numbered ADR files (counted `find docs/decisions -maxdepth 1 -name '[0-9]*.md'`, then `wc -l` on the result → 32, spanning `0001`-`0033` with `0007` missing from the sequence — likely `README.md` was counted as the 33rd "entry"). Matches `PLAN.md`'s own intro claim of a "32-entry ADR system" better than design.md's own number does. Trivial; doesn't affect the portability argument being made. |

No CORRECTED or REFUTED finding above changes the outcome of any gate — all are either cosmetic
(#16, #17) or already fully explained by the correction itself (#13/#14, which are claims the
implementer got *right*, verified independently rather than trusted).

## Pass 2 — adversarial review (2026-08-17, ~03:32-03:55 UTC, separate pass)

Assumed the design is wrong going in and tried to break it. Each item below was checked against
real files, not reasoned about in the abstract.

### (a) Dynamic-discovery guidance in a repo with none of the six conventions

**Real, kept — P2-1 (severity: minor).** `spec-guardian.md` gives clear, doubled guidance:
Rule 1 (`spec-guardian.md:15-17`) says "if none exist, say so explicitly instead of inventing
one," and Rule 6 (`spec-guardian.md:26-27`) independently reinforces "report that plainly and
stop rather than fabricating a verdict to fill the gap." An LLM executing this charter in an
empty-of-convention repo has an unambiguous instruction twice over.

`peer-reviewer.md` is weaker here. Its Rule 1 (`peer-reviewer.md:15-16`) reads: "No fixed repo
layout: review the spec/design/diff the caller names, or else check for `CLAUDE.md`, `AGENTS.md`,
`openspec/`, `docs/decisions/`, `specs/`, `.specify/`" — but unlike `spec-guardian.md`, nothing
in `peer-reviewer.md` explicitly states what to do if *neither* branch produces anything (no
caller-named target *and* none of the six conventions exist). The only backstop is Rule 5's
blanket "never record a verdict for a claim you have not actually checked" (`peer-reviewer.md:
25-26`), which prevents fabrication by omission rather than by an explicit instruction to stop
and say so. In practice this is a narrow scenario — `design.md:74-81` correctly notes the caller
always supplies the review target in the dispatch prompt (these are subagents invoked with a
task description, not autonomously triggered) — but the charter text itself is asymmetric with
its sibling for no stated reason, and the asymmetry is worth closing for consistency.

### (f) Rule 3's own discovery gap (found independently, not in the original attack list)

**Real, kept — P2-2 (severity: minor).** `spec-guardian.md` Rule 3 (`spec-guardian.md:20-21`):
"If this repo has a discoverable protected-path definition, check touched files against it and
flag missing review evidence." Unlike Rule 1, which names six explicit candidate paths in a
fixed order, Rule 3 names zero candidates for what a "protected-path definition" might look
like (this repo's own is `scripts/eval_protected_paths.py` + `.github/CODEOWNERS`; a `spec-kit`
repo or another consumer would use something else entirely, e.g. branch protection rules that
aren't even file-visible). Risk is low because the rule's own fallback is conservative ("never
assume discipline was followed" — silence, not a false claim), but the instruction is
meaningfully less concrete than every other discovery instruction in either charter.

### (b) Risk of spec-guardian / peer-reviewer disagreeing on the same artifact

**Real, kept — P2-3 (severity: major).** Confirmed by direct search: `grep -rniE
"disagree|contradict|conflict|reconcil"` across both charters, the full change package, and
`openspec/AGENTS.md` returns nothing relevant to resolving a disagreement between the two new
charters. `design.md:83-103` ("Two charters, not one") explicitly designs them to ask different
questions but explicitly declines to encode any sequencing or arbitration: "Sequencing them
(`spec-guardian` first, gating a `peer-reviewer` dispatch) is a Phase 5 concern... not encoded in
either charter itself." That deferral would be fine if Phase 5 picked it up, but `PLAN.md`'s own
Phase 5 row (`PLAN.md:157`) only says "compose `openspec/changes/<id>/review.md`... (verdict-first,
two dated passes, refuted attacks kept)" — it names the *shape* of composition, never the case
where `spec-guardian` reports `Verdict: conforms` and `peer-reviewer`'s pass 1/2 findings imply
drift, or vice versa. The gap is real across both phases as currently planned, not just silently
punted from Phase 4 to a Phase 5 that actually addresses it.

Practical impact is bounded — both charters produce independent, read-only prose reports (not an
automated merge/gate decision), so a human reading a contradictory pair would notice and use
judgment, the same as with two disagreeing human reviewers. But nothing today even *names* this
as a known risk anywhere in the package, which is inconsistent with how carefully this package
documents its other known limitations (the dogfood blocker, the protected-path correction).

### (c) The protected-path correction to PLAN.md's Phase 4 table

**CONFIRMED — real, and better-supported than claimed.** Verified independently, not trusted:

- `scripts/eval_protected_paths.py:37-41` lists `"claude-foundation/tests/**"` in
  `PROTECTED_PATTERNS`, with a comment stating it was "missed by the sweep... and was
  unprotected until this entry" — i.e. the source of truth itself documents the exact gap being
  described.
- `python3 -c "from eval_protected_paths import is_protected; print(is_protected(
  'claude-foundation/tests/backwards_compat_baseline.json'))"` → `True`. The other four touched
  files (`README.md`, `CHANGELOG.md`, both `agents/*.md`) all return `False`.
- `.github/CODEOWNERS:22` — `/claude-foundation/tests/ @ianshank` — present, exact match.
- `.github/workflows/quality-gates.yml:43` — `claude-foundation/tests/**` is in the
  `pull_request:` `paths:` filter that re-triggers the protected-path guard.

Beyond what `proposal.md:85-96` cites, I found a second, independent piece of confirming
evidence the implementer didn't cite: `PLAN.md`'s own cross-cutting standards table
(`PLAN.md:34`) already states "any package's `tests/**`" needs the label + CODEOWNERS review —
directly contradicting Phase 4's own table two sections later (`PLAN.md:142`, "Protected: no").
The correction isn't just accurate against the enforcement scripts; `PLAN.md` contradicts itself
internally, which makes catching and stating the correction explicitly (rather than silently
following the wrong "Protected: no") the right call.

### (d) Does openspec/AGENTS.md read coherently in full context?

**CONFIRMED — coherent.** Read the entire file, not just the diff hunk (`openspec/AGENTS.md`,
57 lines). The corrected opening paragraph ("Fleet members are used in their native roles, with
one stated exception: ... Every other row invents nothing," lines 4-9) sets up the two new
`review` rows that follow in the table (lines 21-22), which sit exactly where the paragraph says
they will (between `verify` and `archive`). The new "Staging precondition" paragraph
(lines 25-32) reads as a natural continuation, and correctly generalizes to *all*
`claude-foundation`-sourced rows, not just the two new ones — it explicitly names the three
pre-existing `foundation:*` skill rows and `test-runner` too, closing a gap (unstated staging
precondition) that predates this change. Markdown table integrity checked mechanically
(`awk -F'|' '/^\|/{print NF}'`) — every row has 6 pipe-delimited fields, no broken rows.

### (e) Model choice: sonnet for spec-guardian, opus for peer-reviewer — reasonable, or scope creep?

**Independent judgment: reasonable, not scope creep.** Initially treated this as a likely
overreach (see refuted attack R2 below) but on checking the actual constraint, there is no
stated plan requirement being violated. `PLAN.md`'s Phase 0 §4 "frozen template"
(`PLAN.md:68-70`) fixes frontmatter **field order** ("name, description, tools, model,
maxTurns"), never field **values** — it does not say new charters must reuse `haiku`/`inherit`.
Decision Point 1's "PARITY with `explorer`/`test-runner`" (`PLAN.md:44-46`) is explicitly scoped
to eval rigor ("no scripted eval suite... A higher bar would be a new precedent, not a
gap-fill"), not to model-alias selection. `design.md:105-124` gives a substantive, specific
argument: `explorer`'s `haiku` buys cheap breadth, `test-runner`'s `inherit` tracks the calling
session's trust level for mechanical command execution — neither rationale transfers to a task
that is buying *judgment* (comparing prose claims against code, then trying to break them).
Splitting `sonnet` (bounded, single-pass conformance check) from `opus` (adversarial pass,
explicitly the one place in the fleet built to catch what a lighter pass misses, citing
`add-panel-judge/review.md`'s own second pass finding four further corrections) is a defensible,
documented, differentiated choice — not two agents cargo-culted onto the priciest alias out of
caution. `maxTurns` reuses the repo's only two precedent values exactly (30 matching `explorer`,
40 matching `test-runner`), which shows restraint rather than a pattern of inventing new
precedent wherever convenient.

The one thing worth surfacing as a residual cost note, not a defect: `opus` is the most
expensive alias in `ALLOWED_MODEL_VALUES`, and `peer-reviewer` is designed to run on every
reviewed change once Phase 5 wires it in. That's a real, recurring cost decision a human should
consciously own (mirroring how `add-panel-judge/review.md`'s own "Residual risk" section flags
"cost is N× by construction" for its panel design) — it is not stated anywhere in this package
today.

### Attacks that died under verification (kept per house style)

**R1 — "The `openspec/README.md` 'Current changes' edit is scope creep: `PLAN.md`'s own table
lists 'Index' only under Phase 5 (`PLAN.md:159`), not Phase 4."** Refuted. I extracted and ran
`docs.yml`'s actual index-check logic (`.github/workflows/docs.yml:139-182`) directly against
this tree: it requires *every* non-archived directory under `openspec/changes/` to be linked
from `openspec/README.md`, unconditionally — `openspec index OK; 8 in flight, 4 archived`, and
it would have failed (`in-flight change not linked`) without this edit. The Phase 5 table row
exists because Phase 5 is *also* a new change package needing the same universal treatment, not
because the README-index requirement is Phase-5-specific. This edit was necessary, not scope
creep.

**R2 — "`model: sonnet`/`model: opus` violates Decision Point 1's parity-with-`explorer`/
`test-runner` requirement, which should extend to reusing `haiku`/`inherit`."** Refuted on
rereading the actual text of Decision Point 1 and Phase 0 §4 — see (e) above for the full
derivation. No stated requirement to reuse those two specific model values exists; "parity" is
explicitly about eval rigor.

**R3 — "The binary `Verdict: conforms`/`Verdict: drift` vocabulary is too coarse to represent
'no spec/plan/decision surface could be found.'"** Refuted. `spec-guardian.md` Rule 6
(`spec-guardian.md:26-27`) carves this out as a distinct third state — "report that plainly and
stop" — that skips the `Verdict:` line format entirely rather than forcing an ill-fitting
`conforms`/`drift` label onto a review that couldn't happen.

**R4 — "The change is unmergeable as shipped because `backwards_compat_baseline.json` is a
protected path and this diff carries no `eval-change-approved` label."** Refuted as a defect in
*this* change specifically. `tasks.md:54-62` and `proposal.md:83-96` already state, correctly,
that the eventual PR needs the label and `@ianshank`'s CODEOWNERS review — that's a GitHub
PR-level gate outside what a worktree commit can self-attest, and the package neither claims the
requirement is satisfied nor omits stating it. Nothing to fix here; this is the correction
working as intended.

### (g) The Phase 4 "Proof" (dogfood) requirement — not fabricated, but genuinely unmet

**Real, kept — P2-4 (severity: major, the most substantial finding in this review).** `PLAN.md`'s
Phase 4 table (`PLAN.md:143`) requires: "dogfood: dispatch both charters against Phase 1's
merged diff, producing a real `openspec/changes/harden-quality-gate-integrity/review.md`." The
plan's own "Verification" section (`PLAN.md:242-243`) repeats this as a behavioral acceptance
criterion: "both new charters pass `foundation_tools.validate`, and a dogfood run against
Phase 1's diff produces a non-trivial `review.md`." Neither happened. `openspec/changes/
harden-quality-gate-integrity/` does not exist anywhere in this tree.

I independently verified the stated blocker is real, not a convenient excuse: `git log --all
--oneline` in this worktree surfaces no commit touching Phase 1's stated target
(`skills/quality-gate/scripts/gategen/render.py`'s `_ignored_override_notice` or a
`PYTEST_ADDOPTS` guard); `git branch -a` lists only `main`, this change's own branch, and three
sibling `worktree-agent-*` branches, none titled or related to `harden-quality-gate-integrity`;
`git worktree list` shows the same. Phase 1 genuinely does not exist yet anywhere reachable from
this worktree — it is a sibling, parallel Wave-1 phase (`PLAN.md:168-169`, "zero interdependency
... Land in any order"), and git worktrees do not share each other's unmerged branches.

What earns this "kept, not a defect" rather than "blocking": the gap is handled with real
discipline. `tasks.md:66-76` leaves the checkbox unchecked (`- [ ]`), not fabricated or silently
dropped. `design.md:141-165` ("Dogfood and worktree isolation") documents the exact commands run
to establish the blocker. `proposal.md:55-58` cross-references both from the "What changes"
section rather than staying silent about an incomplete deliverable. The one soft spot:
`CHANGELOG.md:30-31` says "structural validation plus a dogfooded review is the proof" without
the same caveat — see P2-5 below.

### (h) CHANGELOG wording ambiguity

**Real, kept — P2-5 (severity: minor).** `CHANGELOG.md:30-31`: "No eval suite (parity with
`explorer`/`test-runner`, neither of which has one); structural validation plus a dogfooded
review is the proof." Read on its own, without cross-referencing `tasks.md`/`design.md`, this
implies the dogfooded review already happened. It has not (see P2-4). Low stakes — `CHANGELOG.md`
is not the artifact anyone would use to check merge-readiness — but worth a one-clause fix
("...structural validation plus a dogfooded review against a real change is the intended proof;
the dogfood pass is pending Phase 1's diff becoming reachable").

### (i) Stale documentation found independently (not on the original attack list)

**Real, kept — P2-6 (severity: minor).** Three places still describe the plugin's subagent
roster as exactly "explorer, test-runner," unchanged by this commit (confirmed via `git diff
7cdba73..HEAD -- claude-foundation/.claude-plugin/` returning empty, and a direct read of
`architecture.md`):

- `claude-foundation/.claude-plugin/plugin.json:4` — top-level `description`: "...
  least-privilege explorer and test-runner subagents, ..."
- `claude-foundation/.claude-plugin/marketplace.json:14` — plugin entry `description`: "...
  explorer/test-runner subagents, ..."
- `claude-foundation/docs/architecture.md:35` — C4 Level-2 Container line: `Container(agents,
  "Subagents", "Markdown frontmatter", "explorer, test-runner; ...")`

None of these three are part of the documented registration checklist —
`claude-foundation/CLAUDE.md`'s own convention and `PLAN.md`'s Phase 4 "Registration" row
(`PLAN.md:142`) name only `README.md`, `CHANGELOG.md`, and `backwards_compat_baseline.json` — so
this is not a violation of any stated requirement, and `foundation_tools.validate`/`.scan` have
no mechanism to catch stale prose. Worth noting anyway because `design.md:18-25` directly quotes
`docs/architecture.md` while making the portability argument, so the file was open and read
during authoring; the one line in it naming the subagent roster just wasn't touched.

## Residual risk / follow-ups (not blocking)

- **Dogfood proof still owed** (P2-4). Already self-tracked in `tasks.md:68`; complete it once
  `harden-quality-gate-integrity` (or any real merged change) is reachable from the same tree as
  these charters, and commit the resulting `review.md`.
- **Disagreement between `spec-guardian` and `peer-reviewer` is unaddressed** (P2-3). Worth one
  explicit sentence in `design.md` or Phase 5's own proposal naming it as a known case for the
  future composer/dispatcher to resolve, rather than leaving it entirely unnamed.
- **Stale roster descriptions** (P2-6): `plugin.json`, `marketplace.json`, `architecture.md`.
  Cheap fix, three one-line edits.
- **Discovery-instruction asymmetry** (P2-1, P2-2): give `peer-reviewer.md` Rule 1 the same
  explicit "say so, don't invent" clause `spec-guardian.md` states twice; consider naming
  candidate locations (e.g. `CODEOWNERS`) for `spec-guardian.md` Rule 3's "protected-path
  definition" the way Rule 1 names candidates for spec/plan/decision surfaces.
- **`opus` recurring cost** (from (e)): not stated anywhere as a conscious tradeoff; worth one
  line once Phase 5 makes `peer-reviewer` dispatch routine.
- **Cosmetic**: `CHANGELOG.md:30-31` wording (P2-5); `design.md:48`'s ADR count (32, not 33);
  both charters run 1-2 lines past the frozen template's "~20-26" guidance (trivial).

## Overall verdict

**APPROVE WITH FOLLOW-UPS**

What needs fixing, and what does not block merge:

1. **Not blocking, but track to closure:** the Phase 4 "Proof" dogfood deliverable
   (`PLAN.md:143`, `PLAN.md:242-243`) is genuinely outstanding, independently confirmed blocked
   (not fabricated, not skipped silently) by Phase 1 being unreachable from this worktree.
   `tasks.md:68` already tracks this as an open item — keep it open and complete it once Phase 1
   lands, per `design.md:159-165`'s own plan for who does it next.
2. **Not blocking, cheap follow-up:** refresh three stale subagent-roster descriptions
   (`claude-foundation/.claude-plugin/plugin.json:4`, `claude-foundation/.claude-plugin/
   marketplace.json:14`, `claude-foundation/docs/architecture.md:35`) to name `spec-guardian`/
   `peer-reviewer`.
3. **Not blocking, cheap follow-up:** name the `spec-guardian`/`peer-reviewer` disagreement case
   explicitly somewhere (design.md or Phase 5's proposal) instead of leaving it unaddressed.
4. **Not blocking, optional polish:** close the discovery-instruction asymmetries (P2-1, P2-2)
   and the `CHANGELOG.md` wording nit (P2-5).

Nothing found in either pass is a fabricated claim, a schema violation, a hardcoded
monorepo-specific path, a broken gate, or a non-append-only compat change. Every mechanical
check the task asked to be independently re-run (`validate`, `scan`, `backwards_compat`,
`pytest --cov`, `ruff`, `mypy`, `claude plugin validate`, `install_smoke.sh`) passed for real
when I ran them myself, matching the claimed numbers exactly. The one substantive miss (the
dogfood proof) is handled with a level of honesty — unchecked task, documented blocker,
independently reproducible — that argues for trusting the rest of the package's claims rather
than discounting them.
