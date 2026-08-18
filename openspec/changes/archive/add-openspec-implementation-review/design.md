# Design: add-openspec-implementation-review

## Placement

| Concern | Home | Why |
|---|---|---|
| The skill itself | `skills/openspec-implementation-review/` | Mirrors every other full-package skill's shape (`SKILL.md`, `scripts/<pkg>/` + `scripts/run.py`, vendored `validate_skill.py`, `tests/`, `evals/`) — `skills/quality-gate/` and `skills/deploy/` are the closest structural templates |
| Locate / task-completion check | `implreview.locate` | One module, one job: resolve a change id (explicit or inferred) to a directory, and read how done its `tasks.md` looks |
| Dispatch-path detection | `implreview.detect` | Isolated because it is the one module whose correctness this environment cannot fully prove (see "Detecting the dispatch path, honestly," below) — keeping it small and separately tested bounds the unprovable part |
| Prompt composition | `implreview.prompts` | Builds the exact text sent to each dispatch — the one place the two-pass method's *content* lives, so `SKILL.md` and the degraded prompt never drift from each other |
| `review.md` assembly | `implreview.compose` | Create-vs-append is a mechanical decision (see below); this module owns it and nothing else |
| `review.md` structural check | `implreview.validate` | Shared by the skill's own postcondition check and by `tests/` — one definition of "structurally valid," not two |
| CLI wiring | `implreview.cli` + `scripts/run.py` | Argparse subcommands over the library above; `run.py` is a thin `sys.exit(main())` wrapper, matching `skills/deploy/scripts/gen_deploy.py`'s shape |

No engine, registry, or core-model change anywhere in this repo. This is a new skill, full
stop — the same kind of addition `skills/repo-invariant-review` was.

## Detecting the dispatch path, honestly

This is the design problem the brief that produced this change called out explicitly, and it
deserves the same treatment `add-foundation-reviewer-charters/design.md` gave portability: **a
signal that looks confident but cannot actually prove what it claims is worse than one that
admits its limit.**

`claude-foundation/` being present and structurally valid in this tree proves it is *staged*
(ADR 0028) — nothing more. The only thing a Python subprocess can observe that bears on whether
it is *loaded into the current session* is `CLAUDE_PLUGIN_ROOT`, the environment variable
Claude Code populates for a plugin's own hook/script invocations
(`claude-foundation/hooks/hooks.json` reads it directly:
`"${CLAUDE_PLUGIN_ROOT}/hooks/pre_tool_guard.py"`). `implreview.detect.detect_dispatch_path`
therefore checks exactly two things — do both charter files exist, and does
`CLAUDE_PLUGIN_ROOT` resolve to this repo's `claude-foundation/` directory — and recommends
`plugin` only when **both** hold. Absence of either falls through to `degraded`.

**This is deliberately conservative, and the reason is stated in the tool's own output**, not
just in this document: even a `plugin` recommendation is only a filesystem-level proxy for a
session-level fact this process cannot see. `SKILL.md` §2 step 2 and
`references/dispatch-detection.md` both tell the calling agent to independently confirm
`spec-guardian`/`peer-reviewer` actually appear among its own dispatchable subagent types
before trusting the recommendation — the same check the orchestrating session that merged
Phase 4 performed by hand, and the same check this package's own authoring session performed
by hand (see "What was actually tested," below).

### Why not just check for `claude-foundation/agents/*.md` and call it done

Because that is exactly the confusion ADR 0028 exists to prevent: those files being staged on
disk says nothing about the current session. A detector that stopped there would report
`plugin` in every session working this repo directly, unconditionally wrong every single time
— a worse failure mode than reporting `degraded` too often, because it would actively encourage
dispatching a subagent type that does not exist in the caller's own harness.

## The two-pass output shape, recalibrated against real precedent

The first draft of `implreview.validate` required a document to *end* on a distinct
`## Overall verdict` heading, modeled on `openspec/changes/archive/harden-quality-gate-integrity/
review.md`. Checking that assumption against the **other** real, already-merged implementation
review in this repo —
`openspec/changes/archive/test-skill-validator-library/review.md` — falsified it: that file's last
section is `## Residual risk / follow-ups (non-blocking)`; it never repeats its verdict in a
final section. Both are real, both are accepted, APPROVE-WITH-FOLLOW-UPS reviews. A validator
that rejected the second because it lacks something the first happens to have would have been
overfit to one example passed off as "the shape."

The actual invariant both share — and the one `spec-guardian`'s and `peer-reviewer`'s own
charters name directly (Rule 5/6, both: **"Report verdict-first"**) — is that the verdict
appears once, early, under `## Verdict`, unambiguous, before the detailed passes. `implreview.
validate.validate_review_structure` checks exactly that: a `## Verdict` (or `## Overall
Verdict`) heading, positioned before `## Pass 1` and `## Pass 2`, whose own section body states
one of `APPROVE` / `APPROVE WITH FOLLOW-UPS` / `BLOCK`. A trailing restatement is good practice
for a long review (this design's own `SKILL.md` recommends it) but is not mechanically
required, because the tree itself proves it is not universal.

The same recalibration-against-reality applies to "separately dated." A first-draft check
required two *distinct* calendar dates for pass 1 and pass 2. Both real reviews date same-day
passes — `harden-quality-gate-integrity/review.md`'s "Pass 2 — adversarial (2026-08-17, dated
separately per house method)" is explicit that "separately" means separately *labeled*, not
calendar-distinct. `validate_review_structure` checks that each `## Pass N` heading carries its
own `YYYY-MM-DD` annotation, never that the two differ.

`tests/test_validate.py` pins both real files as regression fixtures precisely so a future
change to this validator cannot silently re-introduce either over-fit assumption without a test
failing against real, in-repo ground truth.

## Create vs. append — decided, not left ambiguous

A `review.md` is **never silently overwritten**. `implreview.compose.compose_review`:

- Writes a fresh document (canonical title, a `**Reviewed:** ...` line, then the dispatched
  body) when none exists.
- **Appends** a new, separately dated `## Follow-up review — <date>` section after every
  existing byte when one already exists — the new pass's own headings demoted one level
  (`_demote_headings`, a plain `^##(?!#)` → `###` substitution) so the file stays one coherent
  hierarchy instead of several competing top-level documents concatenated together.
- Only replaces existing content under an explicit `--overwrite` flag, documented in `SKILL.md`
  §4 as the rare, deliberate exception, never the default.

This mirrors a pattern this repo already uses for real:
`openspec/changes/add-panel-judge/review.md` carries its own dated "## Second pass
(2026-08-13)" section, appended to the first draft's findings rather than replacing them.
`compose_review` generalizes that house habit into code instead of leaving it to be re-derived
by hand each time a change gets a follow-up pass. `evals/evals.json`'s
`compose-appends-without-clobbering` case runs this exact round trip twice, via two real
subprocess invocations of `scripts/run.py`, and asserts both passes' distinguishing content
survives in the final file.

## Why the calling agent performs the dispatch, not this skill's scripts

Stated plainly because it is easy to design around by accident: **no module under
`scripts/implreview/` can invoke `spec-guardian`, `peer-reviewer`, or a `general-purpose`
subagent.** Those are tools of the agent harness driving the session, unreachable from a Python
subprocess in the same way `skills/quality-gate`'s generator cannot run the `pytest` command it
writes into `quality-gate.sh` — it writes the script; something else runs it. `implreview.
prompts.build_dispatch_plan` therefore stops at *composing* the prompt(s); `SKILL.md` §2 step 4
is explicit that dispatching them, in order, with the caller's own tools, is a step the skill
names but cannot perform. This is also why `compose_review` never trusts a dispatched body
blindly: it re-derives the canonical title from `--change` rather than the body's own (possibly
slightly wrong) title line, and immediately re-validates the assembled result structurally
before reporting success.

## What was actually tested, and what could not be

Verified, for real, in this authoring session:

- The filesystem-level detection logic (`implreview.detect`), against both synthetic fixture
  directories covering every branch (missing charters, charters present but no env signal, env
  signal present and correctly resolved, a malformed manifest, a symlink loop that turns out to
  raise `RuntimeError` rather than `OSError` from `Path.resolve()` — a real gap the test caught
  and the production code was fixed to handle, not a hypothetical) **and** against this
  session's own real process environment, with no override: `detect_dispatch_path` on the real
  `claude-foundation/` tree, real `os.environ`, lands on `degraded` — the same empirically
  confirmed fact `add-foundation-reviewer-charters/tasks.md` §4 records for the orchestrating
  session that merged Phase 4.
- Every locate/compose/validate code path, via fixture-based fake `openspec/changes/<id>/`
  trees — no live dispatch needed for any of it.
- The degraded path's prompt composition, end to end, including a real two-pass compose round
  trip via `evals/evals.json` (two genuine `python scripts/run.py compose` subprocess
  invocations against the same scratch repo).
- This authoring session's own dispatch capability: a `ToolSearch` for a `Task`/dispatch-style
  tool returned none — this session, itself a spawned worker, has no subagent-dispatch tool of
  its own at all, consistent with the brief's framing that subagent dispatch belongs to an
  orchestrating session, not to every session.

**Not tested, and not claimed to be:** a real `spec-guardian`/`peer-reviewer` dispatch,
end-to-end, through the plugin path. No session working this repo directly can do that today
(see "Why," point 1) — confirmed by the same empirical check this design relies on throughout,
not asserted as a hypothetical limitation.
