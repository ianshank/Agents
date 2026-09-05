# Spec delta: gate-decision-provenance

Capability: a run records what its quality gate decided, and a gate rule can be evaluated and
recorded without blocking — so a threshold that is not yet trusted still produces evidence rather
than silence, and a threshold that is trusted leaves a trace.

## ADDED Requirements

### Requirement: A run records its own gate decision

The system SHALL evaluate the configured quality gate before emitting the run to any sink, and
SHALL carry the decision on the run result. The recorded decision SHALL name, for each evaluated
rule, the scorer, the metric, the observed value, the bound, and whether the rule was met.

Today the decision is computed after the sinks have already fired and exists only as process
output. A run's own record therefore cannot answer "did this pass, and why not" — which makes every
exported artifact incomplete and makes a soak undiffable.

When no gate is configured, the field SHALL be absent from the serialised payload, so a run without
a gate produces byte-identical output to the pre-change shape.

#### Scenario: The decision reaches the sinks

- GIVEN a configuration with at least one gate rule
- WHEN the run completes
- THEN every sink receives a run result carrying the gate decision
- AND the decision is present before the first sink emits

#### Scenario: The decision names what it measured

- WHEN a rule is not met
- THEN its recorded entry carries the scorer, the metric, the observed value and the bound
- AND a reader can reconstruct the comparison without consulting the configuration

#### Scenario: No gate leaves the payload unchanged

- WHEN a configuration declares no gate
- THEN the gate key is absent from the serialised result
- AND the payload is byte-identical to the pre-change output

#### Scenario: The exit code still follows the decision

- WHEN a blocking rule is not met
- THEN the process exits non-zero, as before
- AND the exit code is derived from the same decision that was recorded, not computed separately

### Requirement: A gate rule can be declared advisory

The system SHALL accept an optional boolean on each gate rule marking it advisory. The default
SHALL be false, reproducing the pre-change behaviour, and SHALL be declared on the configuration
model rather than at any call site.

An advisory rule SHALL still require at least one bound. A rule with neither bound can never reach
a verdict, so marking it advisory does not make it meaningful — it makes it a silent no-op wearing
a label, which is the defect the existing bound check was added to prevent.

#### Scenario: The default reproduces existing behaviour

- WHEN no advisory flag is configured on any rule
- THEN every rule is evaluated and filed exactly as before
- AND the emitted result payload is unchanged apart from the recorded decision

#### Scenario: An advisory rule without a bound is still rejected

- WHEN a rule is marked advisory and sets neither `min` nor `max`
- THEN configuration parsing fails with the existing bound-required error
- AND the advisory flag does not suppress that rejection

### Requirement: An advisory rule is evaluated identically and filed differently

The system SHALL compute an advisory rule's verdict through the same evaluation path as a blocking
rule, and SHALL differ only in where the verdict is recorded. A rule flipped from advisory to
blocking SHALL produce the identical verdict on the identical run.

This is what makes a soak worth running. If the advisory path computed anything different from the
blocking path, the soak would be measuring the soak rather than the scorer.

#### Scenario: Advisory and blocking agree on the same run

- GIVEN a run and a rule the scorer's aggregate does not satisfy
- WHEN the rule is evaluated as advisory and then as blocking over the same result
- THEN both produce the same verdict for that rule
- AND only the destination of the verdict differs

#### Scenario: A failing advisory rule does not fail the gate

- WHEN an advisory rule's bound is not met and every blocking rule is met
- THEN the gate result reports passed
- AND the unmet advisory rule appears in the advisory channel and not in the failure list
- AND the process exits zero

#### Scenario: Advisory rules never mask a blocking failure

- WHEN one advisory rule and one blocking rule are both unmet
- THEN the gate result reports not passed
- AND the failure list contains only the blocking rule
- AND the process exits non-zero

### Requirement: Per-rule advisory status is granular, not global

The system SHALL allow advisory and blocking rules to coexist in one gate, and SHALL NOT provide a
mechanism that makes an entire gate advisory from within the harness.

Neutralising a whole gate is already available at the workflow level and is the right tool for
soaking a gate as a whole — the calibrated merge-gate job does exactly this. Duplicating it inside
the harness would add a second way to disarm every threshold at once, including calibrated ones,
which is the outcome per-rule granularity exists to avoid.

#### Scenario: A soak on one rule leaves the others live

- GIVEN a gate with one advisory rule and one calibrated blocking rule
- WHEN the blocking rule is not met
- THEN the run fails
- AND the presence of the advisory rule does not soften that failure

### Requirement: An advisory rule is not gating for the purposes of the calibration guard

`require_calibration_for_judge_gating` refuses a configuration in which a gate rule targets a
judge-backed scorer and no calibration artifact is named. The system SHALL treat only non-advisory
rules as gating for that check.

A judge-backed scorer under an advisory rule is being *measured*, not trusted. Requiring a
calibration artifact before it may be measured makes calibration unreachable, because the labelled
corpus that produces the artifact is assembled from exactly these advisory runs. The fail-closed
refusal stays exactly as strict for every rule that can block.

This is the mechanism `extend-judge-calibration`'s "A judge SHALL remain advisory unless…"
requirement presumes. That change makes an uncalibrated judge unable to gate; this one gives it
somewhere to run in the meantime.

#### Scenario: A judge-backed scorer may be measured without a calibration artifact

- GIVEN a configuration with no `judge_calibration` block
- WHEN its only rule naming a judge-backed scorer is advisory
- THEN the configuration is accepted
- AND the run computes and records that rule's advisory verdict

#### Scenario: The fail-closed refusal is unchanged for blocking rules

- GIVEN a configuration with no `judge_calibration` block
- WHEN any non-advisory rule names a judge-backed scorer
- THEN the configuration is rejected with the existing error
- AND the presence of other advisory rules does not soften that rejection

#### Scenario: Promotion to blocking re-arms the requirement

- GIVEN an advisory rule on a judge-backed scorer in an accepted configuration
- WHEN that rule is changed to blocking and no calibration artifact is named
- THEN the configuration is rejected
