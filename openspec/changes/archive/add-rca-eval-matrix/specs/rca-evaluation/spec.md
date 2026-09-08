# Spec delta: rca-evaluation

Capability: deterministic scoring of a ranked root-cause diagnosis against a finite candidate set —
including whether the agent correctly declines to name a cause when the evidence does not support
one.

## ADDED Requirements

### Requirement: A diagnosis is scored against a declared finite candidate set

The system SHALL score a diagnosis against the candidate-cause set the corpus item declares, and
SHALL NOT infer the candidate set from the agent's own answer. An item SHALL declare its full
candidate set, not only the confirmed cause.

Without the full set, ranked accuracy at k cannot be computed at all: "the confirmed cause appears
in the top k" is meaningless when the population being ranked is unknown. Inferring the set from the
answer is worse than meaningless — it lets an agent define the problem it is being graded on.

#### Scenario: An item without a declared candidate set is rejected

- WHEN a corpus item declares a confirmed cause and no candidate set
- THEN loading the item fails with an error naming the missing field
- AND the run does not silently score it against a set of one

#### Scenario: A named cause outside the candidate set is not silently discarded

- WHEN an agent names a cause that is not in the item's candidate set
- THEN it is scored as incorrect
- AND the evidence records that the answer fell outside the declared set, distinguishing it from a
  wrong choice within the set

### Requirement: Ranked accuracy is reported at more than one cut-off

The system SHALL report accuracy at k for at least the cut-offs 1, 3 and 5, computed per item and
aggregated across the corpus. A single cut-off SHALL NOT be presented as "accuracy" without naming
its k.

Real incidents rarely have exactly one plausible cause, and a top-3 hit is operationally useful in a
way an unqualified single number hides in both directions.

> Attribution note, corrected during review: AC@k and Avg@k are RCAEval's two metrics. **MRR is
> not** — RCAEval §4.2 reads "We currently support two standard metrics: AC@k and Avg@k." Do not
> cite RCAEval for a reciprocal-rank metric.

#### Scenario: Accuracy is reported per cut-off

- WHEN a corpus of diagnoses is scored
- THEN the report carries accuracy at k for k of 1, 3 and 5
- AND each figure is labelled with its k

#### Scenario: A correct cause ranked third

- GIVEN an item whose confirmed cause the agent ranks third
- WHEN it is scored
- THEN accuracy at 1 is 0 for that item
- AND accuracy at 3 and at 5 are both 1

### Requirement: Onset tolerance is evaluated against an explicitly declared timezone

The system SHALL compare a claimed onset time to the item's confirmed onset within a configured
tolerance, and the corpus item SHALL declare the timezone of its timestamps explicitly. A comparison
SHALL NOT rely on an implicit local or system timezone.

This is not defensive pedantry. The reference benchmark for this task records all timestamps in
UTC+8, its own documentation names timezone drift as a leading cause of spurious mismatches, and an
independent replication attributes a 23.3% "Timestamp Error" pitfall rate largely to it. A tolerance
check with an implicit timezone silently scores noise.

The tolerance value SHALL live on a configuration field, not in this requirement.

#### Scenario: An item without a declared timezone is rejected

- WHEN a corpus item carries timestamps and declares no timezone
- THEN loading the item fails with an error naming the missing declaration

#### Scenario: Onset within tolerance is correct

- GIVEN an item whose confirmed onset is a declared instant and a configured tolerance
- WHEN the agent's claimed onset falls within that tolerance of it
- THEN `rca_onset_within_tolerance` scores the item as correct

#### Scenario: A timezone-shifted answer is wrong, not accidentally right

- WHEN a claimed onset matches the confirmed onset's wall-clock reading but in a different declared
  timezone
- THEN the item is scored as outside tolerance
- AND the evidence records both instants normalised to a single timezone

### Requirement: Declining to answer is scored as a first-class outcome

The system SHALL treat "insufficient evidence" as a distinct answer, not as a missing one. On an
item where no candidate cause is correct, an agent that declines and states insufficient evidence
SHALL score as correct; an agent that names any cause SHALL score as incorrect.

The dominant failure mode in this task is confident diagnosis on incomplete evidence — an
independent replication over 1,675 agent runs reports "Hallucination in Interpretation" at 71.2%
and "Incomplete Exploration" at 63.9%, both above 66% and 53% for *every* model regardless of
capability tier. A benchmark that cannot distinguish "I don't know" from a wrong guess cannot
measure the thing that actually goes wrong.

#### Scenario: Correct abstention on an unanswerable item

- GIVEN an item whose candidate set contains no correct cause
- WHEN the agent declines and states that the evidence is insufficient
- THEN `rca_abstention_correctness` scores the item as correct
- AND `rca_ac_at_k` reports "not applicable" rather than zero for that item

#### Scenario: A confident guess on an unanswerable item is penalised

- GIVEN an item whose candidate set contains no correct cause
- WHEN the agent names any cause
- THEN `rca_abstention_correctness` scores the item as incorrect
- AND `rca_false_accusation_rate` counts the named cause

#### Scenario: Abstaining on an answerable item is not free

- GIVEN an item with a confirmed cause in its candidate set
- WHEN the agent declines to answer
- THEN `rca_abstention_correctness` scores the item as incorrect
- AND it is not scored as a correct abstention merely because it named nothing

### Requirement: The corpus carries negative controls

The corpus SHALL contain items on which no candidate cause is correct, and items on which more than
one is. Neither class SHALL be inferable from the item's shape — an unanswerable item SHALL be
indistinguishable from an answerable one until it is diagnosed.

A corpus in which every item has exactly one right answer measures ranking and nothing else, and
rewards a system that always guesses.

#### Scenario: Unanswerable items are present and unmarked

- WHEN the corpus is loaded
- THEN it contains items with no correct candidate
- AND no field visible to the target distinguishes them from answerable items

### Requirement: A trivial baseline is evaluated alongside every agent

The system SHALL provide a deterministic baseline target that ranks candidates by a simple
statistical heuristic over the item's telemetry, and any reported agent result SHALL be accompanied
by that baseline's result on the same corpus.

A 2026 audit across three benchmark families finds untuned statistical baselines competitive with
published RCA methods, with every pairwise comparison reversing sign across subsystems. Its lesson
is that an imported number cannot tell you whether a corpus is separable — only a baseline run on
*that* corpus can. An agent evaluation without one cannot show it is measuring diagnosis rather
than the corpus's own separability.

#### Scenario: The baseline runs on the same corpus

- WHEN an agent is evaluated on this corpus
- THEN the baseline target is evaluated on the identical item set
- AND both results are reported together

#### Scenario: The baseline is deterministic

- WHEN the baseline target runs twice over one item
- THEN it produces identical rankings
- AND it consults no clock, no random source and no network

### Requirement: No threshold in this capability blocks a run before it is calibrated

Every gate rule this change introduces SHALL be advisory. A blocking threshold SHALL be introduced
only by a later, separate change that states the soak evidence it rests on.

#### Scenario: Every introduced rule is advisory

- WHEN the shipped configuration is loaded
- THEN every gate rule naming a scorer from this capability is marked advisory
- AND a run in which all five scorers fail their advisory bounds still exits zero
