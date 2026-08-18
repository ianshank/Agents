# Review: add-openspec-implementation-review

**Reviewed:** tree `87cb068` (base `b441513` on `claude/orbital-drift-agents-reuse-aely36`,
`git merge-base --is-ancestor b441513 HEAD` confirms real ancestry — one commit, linear
history), in two passes — a mechanical fact-check of every falsifiable claim against the
actual tree and real command runs (verdicts CONFIRMED / CORRECTED / REFUTED), and an
adversarial pass that tries to defeat the design and verifies every attack before keeping it.
Refuted attacks are recorded, not deleted. House precedent:
`openspec/changes/add-panel-judge/review.md`. This is an independent review — no
implementer self-report was read; every claim below was re-derived from the tree, from real
command output, or from constructed reproductions run in a scratch copy so the tracked files
were never touched.

## Verdict

**APPROVE WITH FOLLOW-UPS.** Every mechanically-checkable claim in Phase 5's scope holds
exactly as stated: 105 tests / 99.83% branch coverage reproduced verbatim, ruff/ruff-format/
mypy all clean, `validate_skill.py --tier structural,behavioral` OK, the `CLAUDE_PLUGIN_ROOT`
signal is real (genuinely read by `claude-foundation/hooks/hooks.json`, not invented), the
symlink-loop `RuntimeError` handling is real and mutation-tested to be load-bearing, the CLI
run against the real `test-skill-validator-library` change found the real unchecked
`## Archive` box, reported `degraded` for real, and correctly extracted `APPROVE WITH
FOLLOW-UPS` from its real `review.md`. The registration surface (`marketplace.yaml`,
`skills-ci.yml`'s new job, `check_skill_script_drift.py`, `openspec/README.md`'s index, the
`all-skills` EXEMPT reconciliation) all pass when actually executed, not merely read, and the
EXEMPT-exclusion claim was further confirmed non-vacuous by simulating the job's absence and
watching the same check fail. The append-vs-overwrite compose logic survived direct,
repeated, adversarial exercise against a real scratch copy of an existing `review.md` with no
corruption or truncation found anywhere in the `compose`/`validate`/CLI surface itself.

One genuine, verified, non-blocking design gap surfaced under adversarial pressure and is not
mentioned anywhere in `design.md`/`proposal.md`: the degraded-path prompt's own text tells the
dispatched subagent to **write** `review.md` directly and explicitly carves that file out of
an otherwise "read only" instruction — which conflicts with `SKILL.md` step 4's documented
flow of the *calling* agent capturing text output and running `compose` on it. Reproduced
concretely: if a dispatched subagent follows the prompt literally (plausible for any
`general-purpose` agent with Write access) and the orchestrator also runs `compose` on the
same captured text as documented, the result is duplicated content within a single append —
confusing, not silently data-losing, but a real gap in an otherwise carefully-engineered
safety design. Four smaller, cosmetic-severity items are recorded alongside it. None of these
touch the mechanical claims above, none are reachable through any currently-wired CI gate
(this skill is advisory/opt-in, per Decision Point 2), and none require a design change to
fix — all are additive, contained follow-ups.

---

## Pass 1 — mechanical fact-check (2026-08-17)

Every command below was executed directly against the worktree at `87cb068`, not read and
assumed.

| # | Claim | Verdict | Evidence |
|---|---|---|---|
| 1 | 105 tests, all passing | **CONFIRMED** | `cd skills/openspec-implementation-review && python -m pytest tests --cov=implreview --cov-branch --cov-fail-under=95 -q` → 72 + 33 dots = **105 passed**. |
| 2 | 99.83% branch coverage, floor 95% | **CONFIRMED, exactly** | Same run: per-file table shows `cli.py`/`compose.py`/`locate.py`/`prompts.py`/`validate.py` at 100%, `detect.py` at 98% (1 branch), `TOTAL 493 stmts, 1 miss, 110 branch, 0 partial → 99%`; the tool's own summary line reads `Required test coverage of 95% reached. Total coverage: 99.83%` — matches the claim to the decimal. |
| 3 | `ruff check .` clean | **CONFIRMED** | `All checks passed!`, exit 0. |
| 4 | `ruff format --check .` clean | **CONFIRMED** | `16 files already formatted`, exit 0. |
| 5 | `mypy --config-file ../../pyproject.toml scripts/implreview` clean | **CONFIRMED** | `Success: no issues found in 7 source files`, exit 0. |
| 6 | `python scripts/validate_skill.py --skill . --tier structural,behavioral` passes | **CONFIRMED** | `OK: skill passed tier(s) ['behavioral', 'structural'].`, exit 0 — all 7 evals ran for real. |
| 7 | The `CLAUDE_PLUGIN_ROOT` signal genuinely corresponds to real Claude Code plugin-loading behavior, not an invented heuristic | **CONFIRMED** | `claude-foundation/hooks/hooks.json` uses `"${CLAUDE_PLUGIN_ROOT}/hooks/pre_tool_guard.py"` (and two more hook commands) directly, matching `docs/plans/claude-foundation/sources.md:12` citing the official plugin docs (`${CLAUDE_PLUGIN_ROOT}`, `${CLAUDE_PLUGIN_DATA}`, `${CLAUDE_PROJECT_DIR}`). `claude-foundation/.claude-plugin/plugin.json` has `"name": "foundation"`, matching `detect.py:45`'s `_EXPECTED_PLUGIN_NAME = "foundation"` exactly. |
| 8 | The symlink-loop bug (`Path.resolve()` raising `RuntimeError`, not `OSError`) is real, and a test exercises it | **CONFIRMED, and mutation-tested** | Verified empirically on this sandbox's Python 3.11.15: `Path(<self-referencing symlink>).resolve()` raises `RuntimeError: Symlink loop from '...'`, not `OSError`. `tests/test_detect.py:78-86` creates a genuine self-referencing symlink (`loop.symlink_to(loop)`, no monkeypatching) and asserts `detect_dispatch_path` still returns `degraded` cleanly. Further verified the test is load-bearing, not vacuous: removed the `except RuntimeError:` clause from `detect.py` and reran the test — it fails with an **uncaught `RuntimeError`** propagating out of `detect_dispatch_path`; restored the file afterward (`git status --porcelain` clean throughout). |
| 9 | CLI run against a real, already-landed change (`test-skill-validator-library`) behaves as claimed | **CONFIRMED, all three sub-claims** | `locate --change test-skill-validator-library` → `tasks.md: 15/16 checked (incomplete)`, names the one unchecked item, which sits under a real `## Archive` heading in `openspec/changes/test-skill-validator-library/tasks.md:120`. `detect` against the real tree with the real process environment → `recommended_path: degraded` (no `CLAUDE_PLUGIN_ROOT` set in this session). `validate --change test-skill-validator-library` → `verdict: APPROVE WITH FOLLOW-UPS`, correctly extracted from the real `review.md`'s `## Verdict` section. |
| 10 | `skills/marketplace.yaml`, `.github/workflows/skills-ci.yml`'s new job, and `openspec/README.md`'s index entry are syntactically valid and consistent | **CONFIRMED** | `python scripts/skill_marketplace.py validate` → `Skill marketplace OK ✓`. `python scripts/check_skill_script_drift.py` → `OK - 18 copy/copies match their canonical source` (up from 17, one new vendored copy registered). `openspec/README.md:96-97` links `changes/add-openspec-implementation-review/`. The `all-skills` job's own embedded reconciliation script was extracted verbatim from `.github/workflows/skills-ci.yml` and run directly against the real tree: `skill-coverage: OK - 14 skill(s) registered and CI-covered.` — `openspec-implementation-review` needs no `EXEMPT` entry because its job name (`skills-ci.yml:342`) matches the skill directory name exactly. |
| 11 | The vendored `scripts/validate_skill.py` is byte-identical to the canonical root copy | **CONFIRMED** | `diff scripts/validate_skill.py skills/openspec-implementation-review/scripts/validate_skill.py` → empty. |
| 12 | Evals: 7 cases, including a real subprocess round trip that exercises create-then-append | **CONFIRMED** | `evals/evals.json` has exactly 7 entries (`no-such-change`, `locate-happy-path`, `locate-incomplete-tasks-blocks-by-default`, `locate-incomplete-tasks-allow-override`, `detect-degraded-without-foundation`, `validate-hand-written-review-fixture`, `compose-appends-without-clobbering`). The last case's `setup.py` performs a real first `compose` subprocess call, and its own `run` performs a second, real subprocess call against the same scratch repo — read directly, not assumed. |
| 13 | Base ancestry is clean; no unrelated files touched | **CONFIRMED** | `git merge-base --is-ancestor b441513 HEAD` succeeds; `git log --oneline b441513..HEAD` shows exactly one commit (`87cb068`). Full diff stat (42 files) touches only `skills/openspec-implementation-review/**`, `.github/workflows/skills-ci.yml`, `openspec/README.md`, `skills/README.md`, `skills/marketplace.yaml`, `scripts/check_skill_script_drift.py`, and `openspec/changes/add-openspec-implementation-review/**` — exactly the Phase 5 table's file list, nothing else. |
| 14 | No `features.yaml`/ADR change needed (proposal.md's stated non-goal) | **CONFIRMED** | `git show 87cb068 --stat` contains no `features.yaml` or `docs/decisions/` hits — consistent with `proposal.md`'s "no ADR... no `features.yaml` F-ID" reasoning, which mirrors `add-foundation-reviewer-charters`'s precedent for the same call. |
| 15 | The `review.md` structural validator requires verdict-first reporting, not a terminal "Overall verdict" heading, because the two real precedent reviews differ in shape | **CONFIRMED** — see Pass 2(b) below for the direct file-by-file verification | `implreview/validate.py:1-24`'s docstring states the claim; independently re-derived by reading both real files myself (Pass 2b). |
| 16 | This skill's library code never itself performs a subagent dispatch | **CONFIRMED** | `grep -rn "subprocess\|Popen" scripts/implreview/*.py` shows `subprocess` used only in `locate.py` for `git` commands (`branch --show-current`, `log`, `rev-parse HEAD`); no reference to `claude`, `Task`, or any dispatch mechanism anywhere in the library. |

---

## Pass 2 — adversarial (2026-08-17, dated separately per house method)

Assume the design is wrong; try to prove it. Each attack below was executed against the real
tree or a disposable scratch copy, not reasoned about in the abstract.

### (a) The degraded-path prompt: would a real dispatch actually produce a correct `review.md`?

**Confirmed real gap — MAJOR, but non-destructive of prior content.**

Generated the actual prompt the CLI emits (`python scripts/run.py plan --change
test-skill-validator-library --force-path degraded`) and read it exactly as a receiving LLM
would, with no other context. It is largely well-built: it explains *why* the degraded path is
being used (ADR 0028), inlines the full two-pass method with the CONFIRMED/CORRECTED/REFUTED
vocabulary, names the target files to read, and specifies the exact output shape with worked
section headings.

The gap: the prompt's own words tell the receiving LLM to **write the file itself**. Two
lines, read together, in the exact order they appear in the real generated prompt:

- `"Read only; do not edit any file this review is not itself the output of."`
  (`prompts.py:189`) — which specifically *exempts* the review file from a read-only
  restriction, i.e. grants permission to write it.
- `"Write the result to {review_path} in exactly this shape..."` (`prompts.py:38-39`, the
  `_OUTPUT_SHAPE` template) — an imperative instruction, addressed to the dispatched agent,
  naming the exact real path (e.g.
  `/home/user/Agents/.claude/worktrees/agent-a4ae4f1a71d66d576/openspec/changes/
  test-skill-validator-library/review.md` in my own real `plan` run).

This directly conflicts with `SKILL.md` §2 step 4's documented flow: *"Dispatch, for real,
with your own tools... Capture each dispatched agent's full text output"* — followed by step
5, *"Compose `review.md`... Assembles `openspec/changes/<id>/review.md`"* — which assumes the
**calling** agent is the sole writer, via `compose`, never the dispatched agent itself.
Nothing in the prompt or in `SKILL.md` tells the dispatched agent not to use its own Write
tool, and a `general-purpose` subagent plausibly has one.

**Reproduced the concrete failure, not just the ambiguity.** In a scratch repo: (1) simulated
a dispatched agent taking the prompt literally by writing a complete, valid review body
directly to `review.md`; (2) then — exactly as `SKILL.md` step 5 instructs the orchestrator to
do with "the dispatched agent's full text output" — ran `compose --body-file <the same
text>` against that same path. Result: `compose` correctly sees the file already exists and
appends (per its own, correctly-working, non-destructive design — see (c) below), but because
the file already contained that exact content from step 1, the same content now appears
**twice** in one file (`grep -c DUPLICATE-MARKER-999` → 6, up from 3 in the source body), and
`validate` reports **`ok: True`** throughout — the structural checker only ever looks at the
*first* `## Verdict`/`## Pass 1`/`## Pass 2` occurrence (by design, to support the legitimate
multi-pass-over-time case), so it cannot distinguish an intentional dated follow-up from an
accidental duplicate of the same pass.

**Why this is real but not a blocker:** (1) it requires a dispatched agent to actually have
file-write tool access and to interpret "write the result" literally as "use your own Write
tool," which a well-behaved `general-purpose` agent reading `SKILL.md`'s own framing (supplied
by the calling agent around the dispatch, not shown in the prompt object itself) might avoid;
(2) no **prior**, pre-existing review content is ever lost in this scenario — the duplication
is confined to the single new pass being composed, not a corruption of history (see (c)); (3)
this skill is advisory/opt-in (Decision Point 2), not CI-gated, so a duplicated section would
be caught by a human or the next reviewer reading the file, not silently shipped. **Recorded
as a follow-up:** reword the `_OUTPUT_SHAPE` instruction to something like *"Respond with the
review body below as your final answer; do not write any file yourself — the calling agent
will assemble and write `review.md` via `compose`,"* and/or have `SKILL.md` step 4 explicitly
tell the calling agent to instruct the dispatched subagent not to write files.

**Secondary, minor observation from the same reading:** the prompt gives the LLM an explicit
fallback for the tree SHA ("confirm it with `git rev-parse HEAD` if you have shell access,
otherwise state you are trusting the given value") but gives no equivalent fallback for
"today's date," used verbatim in the `## Pass 1 -- ... (<date>)`/`## Pass 2 -- ... (<date>)`
headings. In practice a Claude Code session's system context typically carries the real
current date (as this reviewing session's own context does), so this is unlikely to bite, but
it is asymmetric with the SHA handling and worth a one-line mention for completeness. Low
severity, not verified as an actual failure (no reproduction attempted — this is a documented
observation, not a confirmed defect).

### (b) Verifying the "recalibrated against two real, differing precedents" claim

**CONFIRMED, by directly reading both files.**

Read `openspec/changes/harden-quality-gate-integrity/review.md` in full: it ends with a
distinct, file-final `## Overall verdict` heading (lines 427–453), restating **APPROVE WITH
FOLLOW-UPS** and listing four numbered follow-ups.

Read `openspec/changes/test-skill-validator-library/review.md` in full: it has **no** such
heading anywhere. Its last section is `## Residual risk / follow-ups (non-blocking)` (starting
line 245), and the document ends there — the verdict is stated exactly once, under `##
Verdict` near the top (line 16), never restated.

The claim in `implreview/validate.py`'s module docstring and `design.md`'s "The two-pass
output shape, recalibrated against real precedent" section is accurate: a validator requiring
a terminal "Overall verdict" heading would genuinely reject the second file, a real, accepted,
already-merged review. `tests/test_validate.py:179-206` pins both real files (plus
`add-panel-judge/review.md` as a documented non-match) as regression fixtures — independently
re-run as part of the full suite in Pass 1, all pass.

### (c) Stress-testing the append-vs-overwrite decision against a real scenario

**Attack refuted — the compose/CLI surface itself is safe; no corruption or truncation path
found.**

Copied `openspec/changes/test-skill-validator-library/review.md` (the one real change with an
existing `review.md`) into a scratch repo (`sha256sum` matched the tracked file exactly before
starting). Ran the real CLI's `compose` subcommand against the scratch copy with a
newly-constructed follow-up body:

- **Single append:** `compose` reported `appended:`, and the first `stat -c%s`-worth of bytes
  of the resulting file were byte-for-byte identical (`diff` empty) to the original 263-line
  file; `validate` still reported the *original* top-level verdict (`APPROVE WITH
  FOLLOW-UPS`), not the new follow-up's own (`APPROVE`) — correct, because `_demote_headings`
  moves the follow-up's `## Verdict` to `### Verdict`, which the validator's heading regex
  (`^##\s+...`) does not match.
- **Double append (append-onto-append):** ran `compose` a second time against the
  already-once-appended file. The original 263-line prefix was still byte-for-byte intact
  after two appends; the file grew to 321 lines with two `## Follow-up review` headings;
  `validate` still passed.
- **Empty/malformed body against a fresh change:** ran `compose` with an empty body file
  against a change with no prior `review.md`. It still **created** the file (title + reviewed
  line only) and reported `structural validation FAILED` with all three missing-section errors
  listed on stderr, exit 1 — exactly the documented "never silently drops output" behavior.
- **The real tracked file:** confirmed untouched throughout every experiment above
  (`sha256sum` identical before and after; `git status --porcelain` empty).

No input constructed in this pass caused the compose/CLI surface to silently corrupt,
truncate, or lose any byte of prior content. The only content-duplication risk found in this
review lives in the prompt-design ambiguity in (a) above — a different mechanism (a dispatched
agent writing outside the tool's own control), not a defect in `compose_review` itself.

### (d) Risk of name/behavior confusion with `openspec-peer-review`

**Real, but minor, and one-directional.**

`skills/openspec-implementation-review/SKILL.md:18-22` explicitly disambiguates itself from
`openspec-peer-review` in a dedicated paragraph ("Not a duplicate of `openspec-peer-review`...
If the target hasn't been implemented yet, use `openspec-peer-review` instead"), and its own
marketplace/SKILL.md description leads with "shipped"/"after landing"/"merged" language that a
careful reader or an agent matching skill descriptions would likely use to route correctly.

However, the disambiguation is **one-directional**: `grep -n
"openspec-implementation-review" skills/openspec-peer-review/SKILL.md` finds nothing —
`openspec-peer-review/SKILL.md`'s own description was not updated with a forward-pointing
cross-reference. A contributor who encounters `openspec-peer-review` first (e.g., browsing
`skills/marketplace.yaml` or `skills/README.md`'s table, both list `openspec-peer-review`
before `openspec-implementation-review` alphabetically-ish) has no signal from that skill's own
documentation that a post-implementation counterpart now exists, and would have to already
know to look for it. This is a real, verified, minor documentation gap — not a functional
overlap (the two skills' code paths, output artifacts, and triggers are genuinely distinct,
confirmed by reading both `SKILL.md` files) — worth a one-line follow-up addition to
`openspec-peer-review/SKILL.md`.

### (e) Is the new `skills-ci.yml` job actually correctly excluded from needing an `EXEMPT` entry?

**Refuted (the claim holds) — verified by running the real reconciliation logic, both
positively and negatively.**

Extracted the exact embedded Python block from `.github/workflows/skills-ci.yml`'s
`all-skills` job ("Every skill is registered and CI-covered" step) verbatim and ran it against
the real tree: `skill-coverage: OK - 14 skill(s) registered and CI-covered.`, exit 0 —
`openspec-implementation-review` is covered via `name in job_names` (its job at
`skills-ci.yml:342` is named exactly `openspec-implementation-review`), not via the `EXEMPT`
dict, which correctly still lists only the three ADR-0030 subjective skills
(`hierarchical-recursive-brainstorm`, `openspec-quality-plan`, `openspec-peer-review`).

Then proved the check is non-vacuous rather than trusting the green result: re-ran the same
script with `openspec-implementation-review` artificially removed from the discovered
`job_names` set (simulating the job never having been added). It correctly failed:
`skill-coverage: FAIL - 1 issue(s): - openspec-implementation-review: no dedicated job and not
in EXEMPT`, exit 1. The claim "confirms correct classification" is not just read and trusted —
it is independently, mechanically demonstrated to be a real, working guard.

### Attacks that died under verification (kept per house style)

**"The `Confidence` type's `'low'` literal being unreachable suggests the detection logic has
an untested branch."** Refuted as a coverage concern, kept as a trivial cosmetic note.
`detect.py:38` declares `Confidence = Literal["low", "medium"]`, but grepping all three
`DispatchDetection(...)` construction sites (`detect.py:116,131,147`) shows every branch
returns `confidence="medium"` — "low" is a genuinely unused literal member, not an untested
code path (there is no code path that would produce it). Harmless: a `Literal` type is allowed
to have members no call site currently produces; mypy accepts it because the field's
*declared* type is a superset of what's *actually* assigned. No test gap, no behavior gap —
purely a one-word type-annotation trim available for later, not worth its own follow-up.

**"`_demote_headings` might mis-demote or double-demote nested headings, corrupting document
structure on append."** Refuted for the tested case, but surfaced a real, minor, related
finding kept below (not the same claim, so not deleted, distinguished from it). Constructed a
follow-up body containing both `##` and `### ` headings and appended it to a real scratch
review: the regex (`^##(?!#)`, exactly two hashes, not three) correctly demoted only the `##`
lines to `###`, leaving the already-`###` line untouched — no double-demotion, no corruption,
document remained valid Markdown, `validate` still passed. The **residual** finding (not a
refutation, a narrower true positive) is that this correct, narrow behavior has a nesting-
fidelity cost: a follow-up body that reuses one of this repo's own real precedent shapes
(`add-panel-judge/review.md`'s `### Edge cases the first draft did not specify`,
`test-skill-validator-library/review.md`'s `### Real-timeout claim, verified directly` — both
nested one level under a `##` pass heading) would, after append, have its `###` sub-heading
sitting as a **sibling** of the newly-demoted `### Pass 2` heading rather than nested under it
— a flattened hierarchy, not a corrupted one. Purely cosmetic; recorded as a minor follow-up,
not a defect.

**"A change whose `tasks.md` has deliberately-unchecked, documented follow-on items (like this
very change's own § 7) would be silently treated as 'ready' by `locate`, hiding real
incompleteness."** Refuted, and confirmed reflexively. Ran `locate --change
add-openspec-implementation-review` (this package's own change, dogfooding on itself): it
correctly reports `tasks.md: 37/39 checked (incomplete)`, names both unchecked items verbatim
(the plugin-path-dispatch and retroactive-backfill follow-ons from `tasks.md` § 7), and exits
1 — exactly the documented "no silent default" behavior, applied without any special case for
the tool's own authoring change. A caller who actually wanted to review this change today would
need `--allow-incomplete`, which is the correct, honest outcome given two items are genuinely
still open by design.

---

## Residual risk

- **[MAJOR] Degraded-path prompt instructs direct file-writing, in tension with the documented
  calling-agent-mediated `compose` flow** (Pass 2, attack a). Reproduced concretely: a literal
  reading by a Write-capable dispatched agent, combined with the orchestrator correctly
  following `SKILL.md` step 5, produces duplicated content within one append cycle. No prior
  content is lost in any reproduction; `validate` does not catch the duplication because it
  only inspects the first occurrence of each required section by design. Fix is contained:
  reword the prompt (and/or `SKILL.md` step 4) to make explicit that the dispatched agent
  should return the review text, not write the file itself.
- **[MINOR] One-directional skill disambiguation** (Pass 2, attack d): `openspec-peer-review/
  SKILL.md` has no forward pointer to the new skill. Cheap, optional follow-up.
- **[MINOR] Heading-nesting fidelity on append** for a follow-up body that itself uses `###`
  sub-headings (as both real precedent reviews do) — becomes a sibling of the demoted section
  rather than nested under it. Cosmetic only; no data loss, no invalid Markdown.
- **[TRIVIAL] `detect.py`'s `Confidence` type declares an unreachable `"low"` literal member**
  (every real path returns `"medium"`). No behavior or coverage impact.
- **[TRIVIAL] A double blank line at `.github/workflows/skills-ci.yml:381`**, between the new
  `openspec-implementation-review` job and the `all-skills` job. Whitespace only.
- **Unchanged from the proposal's own stated non-goals, not new findings:** a real
  `spec-guardian`→`peer-reviewer` plugin-path dispatch remains genuinely untested end-to-end,
  because no session working this repo directly can perform one today (ADR 0028) — confirmed
  again in this review's own environment (no `CLAUDE_PLUGIN_ROOT`, `detect` lands on
  `degraded`), not merely trusted from the implementer's claim.

## Overall verdict

**APPROVE WITH FOLLOW-UPS.**

Every mechanical claim about tests, coverage, linting, type-checking, the plugin-detection
signal's real-world grounding, the symlink-loop fix, the CLI's behavior against a real
already-landed change, and the CI/marketplace/index registration surface was independently
re-derived against the real tree and holds exactly as stated — nothing in Pass 1 required a
correction. The two specific recalibration claims singled out for adversarial scrutiny (the
verdict-first validator shape, and the `all-skills` EXEMPT-exclusion) were each verified
directly against primary sources (the two real `review.md` files; the real reconciliation
script, run both positively and with the job artificially removed) rather than taken on faith,
and both held. The append-vs-overwrite compose logic, the design's own most safety-critical
piece, survived repeated, adversarial, real-subprocess exercise with no corruption or
truncation path found.

**Follow-ups for a later change (none blocking this merge):**
1. Reword the degraded-path prompt (`implreview/prompts.py`'s `_OUTPUT_SHAPE` and/or
   `SKILL.md` §2 step 4) so a dispatched subagent is told to return the review text rather than
   write `review.md` itself, closing the duplicate-content risk demonstrated in Pass 2 attack
   (a).
2. Add a one-line forward cross-reference from `openspec-peer-review/SKILL.md` to
   `openspec-implementation-review`, closing the one-directional disambiguation gap in Pass 2
   attack (d).
3. Optional, cosmetic: trim the unused `"low"` member from `detect.py`'s `Confidence` literal;
   fix the double blank line at `skills-ci.yml:381`.
4. Once `claude-foundation` is plugin-loadable in a real session (ADR 0028 M7, or a
   deliberately `--plugin-dir`-started session), exercise the plugin dispatch path end-to-end
   for the first time and confirm the `spec-guardian`/`peer-reviewer` prompts produce the same
   output shape the degraded path already proves — this change correctly does not claim that
   proof today.
