# Spec delta: openspec-implementation-review

Capability: a skill that reviews a *shipped* OpenSpec change's implementation against its own
proposal/design/tasks/spec, producing a dated, two-pass `openspec/changes/<id>/review.md` —
dispatching `claude-foundation`'s `spec-guardian` then `peer-reviewer` charters when that
plugin is actually loaded into the calling session, and degrading to a `general-purpose`
subagent with the same two-pass method inlined when it is not.

## ADDED Requirements

### Requirement: A change is located by explicit id or inferred, never fabricated

The system SHALL locate `openspec/changes/<id>/` for an explicit id, or infer an id from the
current git branch name or recent commit subjects when none is given, using only ids that
correspond to a real directory under `openspec/changes/`. It SHALL never invent or guess an id
that does not exist on disk.

#### Scenario: An explicit id that exists locates cleanly

- WHEN `locate` is given a change id matching a real `openspec/changes/<id>/` directory
- THEN it reports that directory, whether `tasks.md` exists, and whether every checkbox in it
  is checked

#### Scenario: An explicit id that does not exist fails loudly

- WHEN `locate` is given a change id with no matching directory under `openspec/changes/`
- THEN it exits non-zero
- AND its output states plainly that no such change exists, naming the id that was not found

#### Scenario: Inference prefers the branch name, then recent commit subjects

- WHEN no change id is given, and the current branch name contains a real change id as a
  hyphen-or-boundary-delimited token
- THEN that id is used, and the result records that it was inferred from the branch

#### Scenario: Inference falls back to commit subjects when the branch does not match

- WHEN no change id is given, the branch name matches no real change id, and a recent commit
  subject contains one
- THEN that id is used, and the result records that it was inferred from a commit subject

#### Scenario: Inference that finds nothing fails loudly, not silently

- WHEN no change id is given and neither the branch name nor any scanned commit subject
  matches a real change id
- THEN the system reports that inference failed and an explicit id is required
- AND it does not proceed with a fabricated or guessed id

### Requirement: An incomplete change blocks by default, with a documented override

The system SHALL treat a change whose `tasks.md` has any unchecked box as not ready for review
by default, reporting which items are unchecked and exiting non-zero, unless the caller
explicitly opts in to reviewing an incomplete change.

#### Scenario: A fully checked-off change proceeds

- WHEN a located change's `tasks.md` has at least one checkbox and every checkbox is checked
- THEN the system reports it as complete and does not block

#### Scenario: An incomplete change blocks unless explicitly overridden

- WHEN a located change's `tasks.md` has at least one unchecked checkbox
- THEN the system exits non-zero and names the unchecked items
- AND passing an explicit override flag makes the same change proceed instead

### Requirement: The dispatch path is detected from a real, narrow signal, never assumed

The system SHALL recommend the `plugin` dispatch path only when both `claude-foundation`'s
`spec-guardian` and `peer-reviewer` charter files exist in the tree AND the `CLAUDE_PLUGIN_ROOT`
environment variable, if set, resolves to that same `claude-foundation/` directory. Absence of
either SHALL produce a `degraded` recommendation. The system SHALL NOT treat the charter files'
mere presence on disk as sufficient evidence that the plugin is loaded into the current session.

#### Scenario: Charter files present, no environment signal, is degraded

- WHEN `claude-foundation/agents/spec-guardian.md` and `.../peer-reviewer.md` both exist in the
  tree AND `CLAUDE_PLUGIN_ROOT` is unset or does not resolve to `claude-foundation/`
- THEN detection recommends the `degraded` path
- AND its reported reason distinguishes "staged in this tree" from "loaded into this session"

#### Scenario: Charter files present and the environment signal resolves correctly, is plugin

- WHEN both charter files exist AND `CLAUDE_PLUGIN_ROOT` is set to a path that resolves to this
  repo's `claude-foundation/` directory
- THEN detection recommends the `plugin` path
- AND its reported reason states this signal is necessary but not sufficient, and that the
  caller should independently confirm the charters are among its own dispatchable subagent
  types before dispatching by name

#### Scenario: Either charter file missing forces degraded regardless of environment

- WHEN `claude-foundation/agents/spec-guardian.md` or `.../peer-reviewer.md` (or both) is
  absent from the tree
- THEN detection recommends the `degraded` path even if `CLAUDE_PLUGIN_ROOT` is set to a path
  that would otherwise resolve correctly

### Requirement: The degraded dispatch prompt is fully self-contained

The system SHALL compose a single prompt for a `general-purpose` subagent, for the degraded
path, that inlines the complete two-pass review method (mechanical fact-check with
CONFIRMED/CORRECTED/REFUTED verdicts, then a separately labeled adversarial pass that keeps
refuted attacks rather than deleting them) and the exact required output shape, such that a
reader with only that prompt — no charter, no other document — can reproduce the method.

#### Scenario: The degraded prompt names every required method element

- WHEN the degraded dispatch prompt is composed for a change
- THEN it names the two passes, the CONFIRMED/CORRECTED/REFUTED verdict vocabulary, the
  requirement to keep refuted attacks rather than delete them, the target change's id and
  directory, and the exact section headings the output must contain

### Requirement: `review.md` is never silently overwritten

The system SHALL, when composing a review for a change whose `review.md` does not yet exist,
create it in the canonical shape; when one already exists, it SHALL append a new, separately
dated follow-up section after all existing content rather than replacing it, unless the caller
explicitly requests an overwrite.

#### Scenario: Composing against a change with no existing review.md creates one

- WHEN `compose` is run for a change whose `openspec/changes/<id>/review.md` does not exist
- THEN a new file is written containing the canonical title, a reviewed-line, and the
  dispatched body

#### Scenario: Composing against a change with an existing review.md appends, not overwrites

- WHEN `compose` is run for a change whose `review.md` already exists, and no overwrite flag is
  given
- THEN every byte of the existing file's content is preserved
- AND a new, dated `## Follow-up review` section is appended after it

#### Scenario: An explicit overwrite request replaces the file instead

- WHEN `compose` is run with an explicit overwrite flag for a change with an existing
  `review.md`
- THEN the prior content is replaced by the newly composed document

### Requirement: A produced `review.md` is structurally checkable, calibrated against real precedent

The system SHALL validate that a `review.md` opens with `# Review: <id>`, states its verdict
under a `## Verdict` heading before its `## Pass 1` and `## Pass 2` headings (verdict-first,
not verdict-last), and that each pass heading carries its own date. The system SHALL NOT
require a distinct final "Overall verdict" heading, and SHALL NOT require the two passes' dates
to differ, because at least one real, already-merged review in this repository's own history
satisfies neither of those stricter conditions while remaining a valid, accepted review.

#### Scenario: A document matching the shape of this repo's own real reviews validates

- WHEN a `review.md` opens with the correct title, states a canonical verdict token under an
  early `## Verdict` heading, and has dated `## Pass 1` and `## Pass 2` headings in order
- THEN structural validation reports it valid, regardless of whether a further "Overall
  verdict" section exists or the two passes share the same calendar date

#### Scenario: A verdict stated after the passes fails validation

- WHEN a `review.md`'s `## Verdict` heading appears after its `## Pass 1` heading
- THEN structural validation reports it invalid, citing verdict-first reporting

#### Scenario: A missing canonical verdict token fails validation

- WHEN a `review.md`'s `## Verdict` section does not contain one of APPROVE, APPROVE WITH
  FOLLOW-UPS, or BLOCK
- THEN structural validation reports it invalid and extracts no verdict

### Requirement: This skill never performs a subagent dispatch itself

The system's library code (`scripts/implreview/`) SHALL NOT invoke `spec-guardian`,
`peer-reviewer`, `general-purpose`, or any other subagent — it SHALL only locate a change,
detect the dispatch path, compose prompt(s), and assemble/validate `review.md`. The actual
dispatch SHALL remain an action the calling agent performs with its own tools.

#### Scenario: No library module contains a subagent-dispatch call

- WHEN `scripts/implreview/`'s modules are inspected
- THEN none of them invokes a subagent-dispatch mechanism; `plan`'s output is prompt text only,
  never a side-effecting dispatch
