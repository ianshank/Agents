---
name: openspec-implementation-review
description: Reviews a shipped OpenSpec change's implementation against its own proposal/design/tasks/spec, producing a dated, two-pass openspec/changes/<id>/review.md (mechanical fact-check, then adversarial attack, verdict-first) — dispatching claude-foundation's spec-guardian then peer-reviewer charters when that plugin is actually loaded, degrading to a general-purpose subagent with the same method inlined when it is not (the common case in this repo today, per ADR 0028). Use this whenever the user asks to review, audit, or sanity-check a change's actual implementation after landing, wants a dogfooded review.md for a merged OpenSpec change, or asks whether shipped work still matches what it claimed to do. Complements openspec-peer-review (which reviews a plan before implementation starts) rather than duplicating it.
validator_version: '2.0'
compatibility: python>=3.10
version: 1.0.0
---

# openspec-implementation-review — dogfooded post-implementation review

Reviews the *shipped implementation* of an OpenSpec change against its own proposal/design/
tasks/spec, in the two-pass shape this repo's own reviews already use by hand
(`openspec/changes/archive/test-skill-validator-library/review.md`,
`openspec/changes/archive/harden-quality-gate-integrity/review.md` — the two real, already-merged
reviews `implreview.validate`'s required shape is actually calibrated against). This is
**advisory, opt-in tooling** — a contributor or agent invokes it on demand. It is not wired
into `CONTRIBUTING.md`, `GOVERNANCE.md`, protected paths, or any CI gate as mandatory.

**Not a duplicate of `openspec-peer-review`.** That skill reviews a *plan* package before
implementation starts and rewrites it to meet quality standards. This skill runs *after* a
change has landed, never rewrites anything, and produces a persistent `review.md` artifact
instead of a plan revision. If the target hasn't been implemented yet, use
`openspec-peer-review` instead.

## 1. Preconditions (input contract)

- An OpenSpec change id is given (`--change <id>`), or is inferable from the current git
  branch name or recent commit subjects — `openspec/changes/<id>/` must actually exist
  either way. `scripts/run.py locate` reports which happened.
- The change's `tasks.md` looks complete: every `- [ ]`/`- [x]` checkbox is checked. This is
  confirmed by `locate` before proceeding — reviewing a change mid-flight is sometimes
  deliberate, so pass `--allow-incomplete` to do it anyway rather than treating this as a
  hard, unconditional block.
- Python 3.10+, stdlib only. `locate`/`detect`/`compose`/`validate` do no network I/O and no
  third-party imports; `locate`'s branch/commit inference shells out to `git` and degrades
  gracefully (empty/`None`) when that fails or isn't available.
- **The calling agent — not this skill's scripts — performs the actual subagent dispatch.**
  Nothing under `scripts/implreview/` can invoke `spec-guardian`, `peer-reviewer`, or a
  `general-purpose` subagent; those tools belong to the agent harness, not to a Python
  subprocess. This skill locates the change, detects which dispatch path looks available,
  composes the exact prompt(s) to send, and assembles the result — the dispatch step itself
  is something *you*, the agent following this skill, do with your own tools.

## 2. Procedure (the E2E steps)

1. **Locate.** `python scripts/run.py locate --change <id>` (or omit `--change` to infer it
   from the branch/recent commits). Confirms the change exists and its `tasks.md` looks done.
   Stop here and report what's missing if it doesn't — do not improvise around a missing
   change or fabricate a review for one that isn't ready.
2. **Detect the dispatch path, then corroborate it yourself.** `python scripts/run.py
   detect`. This checks a real, filesystem-observable signal and recommends `plugin` or
   `degraded` — but the signal is **necessary, not sufficient** (full explanation, including
   exactly what is and isn't checkable from a script:
   `references/dispatch-detection.md`). Before trusting a `plugin` recommendation and
   dispatching `spec-guardian`/`peer-reviewer` by name, independently confirm they actually
   appear among *your own* dispatchable subagent types — `claude-foundation` being present in
   this repo's tree proves it is *staged* (ADR 0028), never that it is *loaded into your
   session*.
3. **Compose the dispatch prompt(s).** `python scripts/run.py plan --change <id> [--force-path
   plugin|degraded] [--out-dir DIR]`. Prints (or writes) the exact prompt(s) for the path
   detected or forced: `spec-guardian` then `peer-reviewer` for `plugin`, or one
   self-contained `general-purpose` prompt with the whole two-pass method inlined for
   `degraded` — the path this repo's own sessions actually exercise today (see
   `references/dispatch-detection.md`).
4. **Dispatch, for real, with your own tools.** Send each prompt from step 3 to the named
   subagent type, in order. For the plugin path, feed `spec-guardian`'s findings into the
   `peer-reviewer` prompt as context (both prompts already say so). Capture each dispatched
   agent's full text output.
5. **Compose `review.md`.** `python scripts/run.py compose --change <id> --body-file
   <dispatched-output.md> --dispatch-path plugin|degraded [--tree-sha <sha>]`. Assembles
   `openspec/changes/<id>/review.md` — creating it fresh, or appending a dated follow-up
   section if one already exists (see §4). Never trust the dispatched text blindly: `compose`
   re-derives the title from `--change` and immediately re-validates the result structurally.
6. **Confirm.** `python scripts/run.py validate --change <id>` (or let step 5's own output
   speak — `compose` already prints the same check). A non-zero exit here means the dispatched
   reviewer's output didn't actually produce the required shape; fix the input and re-run
   `compose`, don't hand-edit around a failed check.

## 3. Output contract (postconditions — what "done" means)

`openspec/changes/<id>/review.md` exists and, checked by `python scripts/run.py validate`
(`implreview.validate.validate_review_structure`):

- Opens with `# Review: <id>`.
- Has a `## Verdict` heading whose opening paragraph states exactly one of the three
  canonical verdict tokens, bolded: **APPROVE**, **APPROVE WITH FOLLOW-UPS**, or **BLOCK** —
  reported **verdict-first**, before the detailed passes (this repo's actual convention, per
  both `spec-guardian`'s and `peer-reviewer`'s own charters' Rule 5/6 — not verdict-last).
- Has a `## Pass 1 — ... (<YYYY-MM-DD>)` heading (mechanical fact-check) before a
  `## Pass 2 — ... (<YYYY-MM-DD>)` heading (adversarial) — each carrying its own date, which
  need not differ from the other's (both real precedent reviews in this repo date same-day
  passes this way; "separately dated" means separately *labeled*, not calendar-distinct).
- Pass 1 gives every falsifiable claim exactly one verdict — CONFIRMED / CORRECTED / REFUTED
  — with evidence. Pass 2 is adversarial and **keeps refuted attacks in the output, marked
  refuted, rather than deleting them.** Neither of these is mechanically checkable (they are
  judgment calls about a specific change's substance) — `validate` checks *shape*, never
  *quality*; see §5.
- Idempotent structure: re-running `compose` against the same change never produces a
  structurally invalid document, whether it creates, appends, or (with `--overwrite`) replaces.

## 4. Failure handling

- **Target change doesn't exist.** `locate`/`plan`/`compose`/`validate --change` all exit
  `2` with `no such change: '<id>' ... known changes: <list>` on stderr. Nothing is written.
- **`tasks.md` isn't fully checked off.** `locate` exits `1` by default, naming the unchecked
  items, unless `--allow-incomplete` is passed — reviewing a deliberately in-flight change is
  a real use case, not an error, but it is never the silent default.
- **`review.md` already exists — decided, not ambiguous.** `compose` **never silently
  overwrites.** It appends a new, separately dated `## Follow-up review — <date>` section
  after every existing byte, with the new pass's own headings demoted one level so the
  document stays one coherent hierarchy — the same pattern this repo's own
  `add-panel-judge/review.md` already uses for its own separately dated second pass.
  `--overwrite` exists for the rare, deliberate case of redoing a bad file; it is never the
  default, and using it should be a conscious choice, not a habit.
- **Dispatched output doesn't come out in the required shape.** `compose` still writes it (it
  never silently drops output) and reports every structural error on stderr with a non-zero
  exit, so the caller can see exactly what's missing and re-dispatch or hand-fix the body
  before trying again — it does not fabricate a passing shape around bad content.
- **Leave clean state, always.** Every write (`compose`, `plan --out-dir`) either succeeds
  completely or leaves prior state untouched; nothing is left half-written.

## 5. Validation gate (before declaring success)

You are **not done** until this exits 0:

```bash
python scripts/validate_skill.py --skill . --tier structural,behavioral
```

## 6. Examples

**Example 1 — dogfooding a real, merged change (historical; the target has since been archived)**
Input, run while `harden-quality-gate-integrity` was still under `openspec/changes/` (tasks.md
already fully checked): `python scripts/run.py locate --change harden-quality-gate-integrity`.
`detect` reports `degraded` (no `CLAUDE_PLUGIN_ROOT`) — see `references/dispatch-detection.md`
for why that's the expected, common case. `plan` prints one `general-purpose` prompt with the
two-pass method inlined, naming the change directory. After dispatching it and capturing its
output, `compose --change harden-quality-gate-integrity --body-file <output> --dispatch-path
degraded` writes (or, since that change already has a real `review.md` from Phase 1's own
independent review, appends a dated follow-up to) `review.md`.
Output: a structurally valid `review.md`, confirmed by `validate`'s exit 0. The artifact now
lives at `openspec/changes/archive/harden-quality-gate-integrity/review.md`. **`locate` only
resolves currently-open changes** — `list_change_ids` deliberately excludes `changes/archive/`
— so re-running this exact command today raises `ChangeNotFoundError`; that is Example 2's
failure mode, not a regression, once a change has been archived.

**Example 2 (edge case) — a bogus change id**
Input: `python scripts/run.py locate --change this-change-does-not-exist`.
Output: exit `2`, stderr reads `error: no such change: 'this-change-does-not-exist' ...
known changes: <the real list>` — no file written, no fabricated report.

---

## Bundled layout

```
openspec-implementation-review/
├── SKILL.md                       # this file
├── references/
│   └── dispatch-detection.md      # the plugin-vs-degraded signal, in full
├── scripts/
│   ├── run.py                     # CLI entrypoint (locate/detect/plan/compose/validate)
│   ├── validate_skill.py          # vendored, byte-identical to scripts/validate_skill.py
│   └── implreview/                # the importable library the CLI wraps
│       ├── locate.py              # find the change dir; read tasks.md completion
│       ├── detect.py              # the plugin-vs-degraded signal
│       ├── prompts.py             # compose the dispatch prompt(s)
│       ├── compose.py             # assemble review.md (create vs. append)
│       ├── validate.py            # review.md structural validator
│       └── cli.py                 # argparse wiring for scripts/run.py
├── tests/                         # unit tests over implreview/ (fixture-based, no live dispatch)
└── evals/
    ├── evals.json
    └── fixtures/                  # fake openspec/changes/<id>/ trees + reviewer-output bodies
```
