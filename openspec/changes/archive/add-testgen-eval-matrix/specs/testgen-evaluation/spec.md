# Spec delta: testgen-evaluation

Capability: deterministic, execution-grounded evaluation of an AI-generated test suite — does it
run, does it detect seeded faults, does it stay quiet on correct code, and does it cover the
obligations it was asked to cover.

## ADDED Requirements

### Requirement: Execution happens in the target, and scorers only read its evidence

The system SHALL execute a generated test suite inside the target, and SHALL expose the result as
structured evidence on the target's output. Every scorer in this capability SHALL be a pure
function of that evidence and SHALL perform no process execution, no filesystem mutation and no
network access of its own.

This mirrors the state-scorer contract already in the tree: the engine computes a
`StateEvaluation`, and `state_transition` reads it without comparing anything itself. Keeping
scorers pure is what makes them deterministic under repeated attempts, safe to run in the offline
suite, and cheap to matrix-cover.

A scorer SHALL report "not applicable" rather than a zero when the evidence is absent. A missing
suite and a suite that killed no mutants are different outcomes, and collapsing them into `0.0`
makes an infrastructure failure indistinguishable from a total agent failure.

#### Scenario: A scorer performs no execution of its own

- WHEN any scorer in this capability scores an item
- THEN it reads only the evidence already present on the target output
- AND it starts no subprocess, opens no socket, and writes to no path outside the run's own outputs

#### Scenario: Absent evidence is not a zero

- WHEN the target output carries no test-generation evidence
- THEN each scorer reports "not applicable" rather than a failing score
- AND the run surfaces the absence as its own signal rather than as four independent failures

#### Scenario: The same evidence yields the same scores

- GIVEN one evidence payload
- WHEN every scorer in this capability scores it twice
- THEN both passes produce identical values
- AND no scorer consults a clock, a random source, or the environment

### Requirement: The suite-execution target is explicitly allowlisted

The system SHALL run the suite-execution target only when it is named in the callable-target
allowlist. The allowlist is deny-by-default, and this target SHALL NOT be added to any default,
implicit or wildcard entry.

Executing model-authored test code is the highest-privilege operation in this capability. It is
gated by the mechanism the repository already built for exactly this class of risk, and it does not
get an exemption for being convenient.

#### Scenario: An unlisted execution target is refused

- WHEN a configuration names the suite-execution target and the allowlist does not contain it
- THEN the run is refused before any generated code is executed
- AND the error names the allowlist as the reason

#### Scenario: The sandbox is bounded

- WHEN a generated suite runs
- THEN it executes under a wall-clock limit and within a working directory created for that item
- AND a suite that exceeds the limit is recorded as a timeout rather than terminating the run

### Requirement: Suite executability is measured before anything else

The system SHALL report whether a generated suite is collectable and runnable at all, separately
from any measure of its quality. A suite that does not import, does not parse, or collects zero
tests SHALL be scored as non-executable, and the remaining scorers SHALL report "not applicable"
for that item.

Ordering matters here: a mutation score computed over a suite that never ran is not a low score,
it is a meaningless one. This is the deterministic gate that keeps the other three honest.

#### Scenario: A suite that does not import is non-executable

- WHEN a generated suite raises during collection
- THEN `test_executability` scores it as failed
- AND `testgen_mutation_score`, `testgen_green_on_correct` and `requirement_obligation_recall`
  report "not applicable" for that item

#### Scenario: A suite that collects zero tests is non-executable

- WHEN a generated suite parses and collects no test functions
- THEN `test_executability` scores it as failed
- AND the evidence records the collected count as zero rather than omitting it

### Requirement: Mutation score is reported in both denominators, and both are named

The system SHALL report two mutation figures for each focal method:

- a **raw** score over all non-equivalent mutants generated for that focal method, and
- a **normalized** score over the non-equivalent mutants the suite actually covers.

Both SHALL exclude equivalent mutants. Neither SHALL be reported alone, and the emitted evidence
SHALL name which denominator each figure used rather than leaving the reader to infer it.

The two answer different questions — "how much of the seeded fault space did this suite catch" and
"of what it reached, how much did it kill" — and a suite can look strong on one while being weak on
the other. Reporting a single unlabelled "mutation score" is how that difference gets lost.

> Attribution note for the implementer, corrected during review: the **normalized** denominator is
> Inozemtseva & Holmes's (ICSE 2014), where it is called a *normalized effectiveness measurement*.
> The **focal-method** raw denominator is not theirs — theirs is project-wide — it is the ISSTA 2026
> replication study's adaptation. Cite both, and do not attribute the focal-method form to
> Inozemtseva.

#### Scenario: Both denominators are emitted

- WHEN a suite is scored against a focal method with seeded mutants
- THEN the evidence carries a raw figure, a normalized figure, and the counts each was computed from
- AND each figure is labelled with its denominator

#### Scenario: A suite that covers little but kills what it reaches

- GIVEN a suite covering a small fraction of the seeded mutants and killing all it covers
- WHEN it is scored
- THEN the normalized figure is high
- AND the raw figure is low
- AND neither figure is presented without the other

#### Scenario: Equivalent mutants are excluded from both denominators

- WHEN the mutant set contains mutants marked equivalent
- THEN neither denominator counts them
- AND the evidence records how many were excluded

### Requirement: False alarms on correct code are scored separately from fault detection

The system SHALL execute each generated suite against the known-correct reference implementation
and SHALL count any failing test as a false alarm. This figure SHALL be reported independently of
mutation score and SHALL NOT be combined into a single quality number.

A suite that fails on correct code is worse than useless — it costs review time on every run and
trains the team to ignore it. A single blended score lets a high mutation score hide it.

#### Scenario: A suite that fails on correct code is penalised

- WHEN a generated suite is executed against the non-buggy reference implementation and one test fails
- THEN `testgen_green_on_correct` records a false alarm for that item
- AND `testgen_mutation_score` is unchanged by it

#### Scenario: False alarms are not averaged into fault detection

- WHEN both scorers have values for an item
- THEN each is emitted as its own named score
- AND no aggregate presented by this capability sums or averages the two together

### Requirement: Obligation recall is measured against a declared gold set

The system SHALL score the fraction of an item's declared atomic obligations that the generated
suite covers, as a value in the closed interval from zero to one. The gold obligation set SHALL be
carried by the corpus item; the scorer SHALL NOT infer obligations from the generated tests.

Inferring the target from the artifact being scored is circular: a suite would define its own
obligations and always score highly.

#### Scenario: Recall is the covered fraction of the declared set

- GIVEN an item declaring four gold obligations
- WHEN the generated suite covers three of them
- THEN `requirement_obligation_recall` reports 0.75

#### Scenario: An item with no declared obligations is not applicable

- WHEN an item carries no gold obligation set
- THEN the scorer reports "not applicable"
- AND it does not report a perfect or a zero score

### Requirement: Suite reliability is measured by repeated attempts, not by a scorer

The system SHALL express suite flakiness through the existing repeated-attempt mechanism — k
independent attempts with `pass^k` over `test_executability` — and SHALL NOT introduce a scorer
that claims to measure variation across attempts.

A scorer sees one attempt. Any scorer purporting to report a flake rate would be reporting
something it cannot observe.

#### Scenario: Flakiness is a reliability metric over an existing scorer

- WHEN a run configures five repetitions and a gate rule with metric `pass_power_k` on
  `test_executability`
- THEN the reliability report carries the per-item `pass^k` for that scorer
- AND no separate flake-rate scorer is registered

### Requirement: No threshold in this capability blocks a run before it is calibrated

Every gate rule this change introduces SHALL be advisory. A blocking threshold SHALL be introduced
only by a later, separate change that states the soak evidence it rests on.

#### Scenario: Every introduced rule is advisory

- WHEN the shipped configuration is loaded
- THEN every gate rule naming a scorer from this capability is marked advisory
- AND a run in which all four scorers fail their advisory bounds still exits zero
