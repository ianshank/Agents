# Spec delta: foundation-reviewer-charters

Capability: two read-only `claude-foundation` agent charters — a spec/plan/decision
conformance reviewer and a two-pass adversarial reviewer — that discover a consumer repo's
own planning conventions at invocation time instead of assuming any one repo's layout.

## ADDED Requirements

### Requirement: A conformance reviewer discovers repo conventions instead of assuming them

The system SHALL provide an agent charter, `spec-guardian`, that checks — in order —
whether `CLAUDE.md`, `AGENTS.md`, `openspec/`, `docs/decisions/`, `specs/`, and `.specify/`
exist in the repo it is invoked in, and SHALL use whichever it finds rather than assuming a
fixed set. The charter SHALL contain no path specific to any one consumer repository.

#### Scenario: Conventions are discovered in the documented order

- WHEN `spec-guardian` is dispatched in a repository that has `AGENTS.md`, `openspec/`, and
  `docs/decisions/` but no `CLAUDE.md`, `specs/`, or `.specify/`
- THEN it uses `AGENTS.md`, `openspec/`, and `docs/decisions/` as the change's
  spec/plan/decision surface
- AND it does not report a `CLAUDE.md`, `specs/`, or `.specify/` finding

#### Scenario: No convention is discoverable

- WHEN `spec-guardian` is dispatched in a repository with none of the six candidate
  conventions present
- THEN it states explicitly that no planning/decision convention was found
- AND it does not invent a convention or fabricate a verdict as if one existed

### Requirement: A conformance reviewer reports a verdict-first, evidence-cited result

The system SHALL have `spec-guardian` open its report with exactly one verdict line reading
`Verdict: conforms` or `Verdict: drift`, followed by numbered findings that each cite a
`file:line` location, ordered most consequential first.

#### Scenario: A drifted change is reported with citations

- WHEN a change's implementation contradicts a concrete claim in its own declared spec,
  plan, or decision document
- THEN the report's first line reads `Verdict: drift`
- AND at least one numbered finding cites the `file:line` of the contradicting code and the
  `file:line` of the claim it contradicts

#### Scenario: A conforming change is reported cleanly

- WHEN every concrete claim in a change's own declared spec/plan/decision documents matches
  the current state of the files it says it touches
- THEN the report's first line reads `Verdict: conforms`

### Requirement: An adversarial reviewer performs two separately labeled passes

The system SHALL provide an agent charter, `peer-reviewer`, whose first pass gives every
falsifiable claim in its target exactly one verdict — CONFIRMED, CORRECTED, or REFUTED, each
with a `file:line` citation as evidence — and whose second pass is reported separately from
the first and attempts to break the design or implementation under review, verifying each
attempted attack against the actual files before counting it.

#### Scenario: Pass 1 assigns exactly one verdict per claim

- WHEN `peer-reviewer`'s pass 1 evaluates a falsifiable claim from the reviewed design or
  proposal against the current code
- THEN the claim receives exactly one of CONFIRMED, CORRECTED, or REFUTED
- AND the verdict is accompanied by a `file:line` citation as evidence

#### Scenario: Pass 2 is adversarial and reported separately from pass 1

- WHEN `peer-reviewer` completes pass 1 and begins pass 2
- THEN pass 2's findings are labeled and reported in a section distinct from pass 1's
- AND each pass-2 attack is verified against the actual files before being kept

### Requirement: Refuted attacks are kept, not deleted

The system SHALL have `peer-reviewer` retain every pass-2 attack it verified and found not
to hold, marked as refuted with the reasoning that refuted it, rather than omitting it from
the final report.

#### Scenario: A refuted attack remains visible in the output

- WHEN a pass-2 attack is investigated and found not to hold against the actual files
- THEN the final report still lists the attack
- AND the attack is marked refuted with the reasoning that refuted it

### Requirement: Both charters are least-privilege, read-only, and non-mutating

The system SHALL grant `spec-guardian` and `peer-reviewer` only `Read`, `Grep`, and `Glob`
tools, and SHALL have neither charter edit, create, or delete any file, or run any command,
while producing its review.

#### Scenario: Neither charter's tool grant permits a write

- WHEN either charter's frontmatter `tools` field is read
- THEN it lists only `Read`, `Grep`, `Glob`
- AND it does not list `Edit`, `Write`, `Bash`, or any other tool

#### Scenario: A charter under review is not modified by reviewing it

- WHEN `spec-guardian` or `peer-reviewer` completes a review of a target change
- THEN no file the charter read during that review has been modified as a result

### Requirement: Both charters register as portable, name-matched, append-only components

The system SHALL have each charter's frontmatter `name` field byte-match its filename stem,
SHALL validate both under the existing plugin-agent frontmatter schema, and SHALL record
their addition in the backwards-compatibility baseline as an addition, never a removal of an
existing component.

#### Scenario: Frontmatter name matches the filename

- WHEN `claude-foundation/agents/spec-guardian.md` and `claude-foundation/agents/peer-reviewer.md`
  are validated
- THEN each file's frontmatter `name` equals its own filename stem exactly

#### Scenario: Registration is additive

- WHEN `foundation_tools.backwards_compat` is run against the tree after both charters are
  added
- THEN `explorer` and `test-runner` still appear in the live agent surface
- AND the diff against the baseline reports `spec-guardian` and `peer-reviewer` as additions,
  never as removals of any existing component
