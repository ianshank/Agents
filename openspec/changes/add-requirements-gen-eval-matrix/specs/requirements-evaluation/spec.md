# Spec delta: requirements-evaluation

Capability: deterministic evaluation of generated requirements against declared gold criteria and
their supporting evidence, with provenance strong enough that any number reported can be re-derived
from the sources it came from.

## ADDED Requirements

### Requirement: Retrieved evidence is recorded with a re-fetchable reference

The system SHALL record, for every retrieved evidence item used in generation, the source type, the
source identifier, the exact reference used to fetch the bytes, and a hash of those bytes. The
recorded reference SHALL be one that resolves to the same content when re-fetched.

A hash over content fetched by a reference that does not pin a version is a change-detector, not a
reproducibility key. It fires when nothing changed and stays silent when the underlying document is
edited between fetches — the worst of both, while looking authoritative.

#### Scenario: A document source is pinned to a revision

- WHEN a revisioned document source is used as evidence
- THEN the recorded reference is revision-scoped, so re-fetching it returns that revision's content
- AND the recorded hash is over the bytes that reference returned

#### Scenario: An unpinnable source is recorded as unpinnable

- WHEN a source cannot be pinned to a version by any available reference
- THEN the evidence record marks it unpinnable and stores the retrieval timestamp
- AND it does not present a content hash as if it were a reproducibility key

#### Scenario: Only obtainable metadata is recorded

- WHEN a source's interface does not expose a field
- THEN that field is absent from the evidence record
- AND no placeholder or inferred value is written in its place

#### Scenario: Provenance is verifiable, not merely present

- GIVEN a run record with evidence items
- WHEN each recorded reference is re-fetched
- THEN every hash matches
- AND a mismatch is reported as a provenance failure rather than a scoring failure

### Requirement: Generated requirements are scored against declared gold criteria

The system SHALL score recall of an epic's declared gold acceptance criteria, as a value in the
closed interval from zero to one. The gold set SHALL be carried by the corpus item and SHALL NOT be
inferred from the generated output.

Inferring the target from the artifact being graded is circular — a generator would define its own
success criteria.

#### Scenario: Recall is the covered fraction of the declared set

- GIVEN an epic declaring eight gold acceptance criteria
- WHEN the generated set covers six
- THEN `req_ac_recall` reports 0.75

#### Scenario: An epic with no gold set is not applicable

- WHEN a corpus item carries no gold acceptance criteria
- THEN the scorer reports "not applicable" rather than a perfect or zero score

### Requirement: Requirements unsupported by retrieved evidence are detected

The system SHALL identify generated requirements that assert scope not supported by any recorded
evidence item, and SHALL report them as a rate. The check SHALL run against the recorded evidence,
not against the generator's own account of what it used.

#### Scenario: An unsupported constraint is flagged

- GIVEN an epic whose evidence mentions no performance target
- WHEN the generated set asserts a latency budget
- THEN `req_scope_hallucination` counts that requirement

#### Scenario: A supported requirement is not flagged

- WHEN every assertion in a generated requirement traces to a recorded evidence item
- THEN it does not count toward the rate

#### Scenario: Contradictory sources do not produce a silent pick

- GIVEN two evidence items that contradict each other on the same point
- WHEN a requirement asserts one of them
- THEN the evidence record shows the contradiction
- AND the run reports it rather than scoring the requirement as cleanly supported

### Requirement: Set diversity is measured to detect mode collapse and routed as a coverage risk

The system SHALL score the internal diversity of a generated requirement set and SHALL treat a value
below the configured floor as a coverage risk requiring escalation, not as a correctness failure.

The measure SHALL be computed **within** one generated set, and the emitted score SHALL name what it
measured.

Two constraints on the measure, both load-bearing:

1. It SHALL be computable offline with no additional runtime dependency. The published diversity
   result this requirement responds to used embedding similarity; this repository's dependency tree
   deliberately excludes numpy from the offline path, and a scorer that needs a network embedding
   call cannot run in the offline suite.
2. The generation temperature used to produce the set SHALL be recorded alongside the score. The
   source study states that raising temperature increases diversity, so a floor is satisfiable by a
   configuration change rather than by better coverage. A diversity score without its temperature is
   not interpretable.

> Scope note, corrected during review: the published finding measures diversity *between* runs of a
> generator, against a comparison group of students, not within a single backlog against experts. It
> motivates measuring this; it does not supply a threshold. The floor is ours to establish.

#### Scenario: Low diversity escalates rather than fails

- WHEN a generated set scores below the configured diversity floor
- THEN the outcome is routed to escalation
- AND the run is not failed on that basis alone

#### Scenario: The score carries its temperature

- WHEN a diversity score is emitted
- THEN the record carries the generation temperature that produced the set
- AND a score recorded without one is reported as uninterpretable rather than compared to the floor

#### Scenario: Diversity is measured within the set

- GIVEN one generated requirement set
- WHEN diversity is scored
- THEN the value is computed over the members of that set
- AND it does not require a second generation run to compute

### Requirement: The epic-to-test chain is measured, never inferred

The system SHALL score whether each generated requirement carries a complete traceability chain to
its acceptance criteria and, where the corpus declares them, to tests. A chain SHALL be counted only
where every link is present; a fluent narrative asserting a link SHALL NOT satisfy it.

Published results for LLM document-to-code traceability sit well below the level at which inference
would be safe, and vary sharply by task framing — one-to-many and many-to-many formulations of the
same task differ by an order of magnitude. Measuring the links directly is the only defensible
option.

#### Scenario: A missing link breaks the chain

- WHEN a requirement has acceptance criteria and no declared test link, and the corpus declares tests
- THEN `req_traceability_closure` counts the chain as incomplete

#### Scenario: An asserted link is not a link

- WHEN generated prose claims a requirement is covered by a test that the corpus does not declare
- THEN the chain is counted as incomplete

### Requirement: No threshold in this capability blocks a run before it is calibrated

Every gate rule this change introduces SHALL be advisory. A blocking threshold SHALL be introduced
only by a later, separate change that states the soak evidence it rests on.

#### Scenario: Every introduced rule is advisory

- WHEN the shipped configuration is loaded
- THEN every gate rule naming a scorer from this capability is marked advisory
- AND a run in which all four scorers fail their advisory bounds still exits zero
