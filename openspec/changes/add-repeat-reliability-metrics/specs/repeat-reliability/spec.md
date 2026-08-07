# Spec delta: repeat-reliability

Capability: repeated independent execution of each evaluation item, with reliability metrics that
distinguish a reliable agent from a lucky one.

## ADDED Requirements

### Requirement: Each evaluation item can run multiple independent attempts

The system SHALL accept a configured positive attempt count k and SHALL execute each selected
evaluation item exactly k times unless a fail-closed resource budget terminates the run.

The default SHALL be 1, reproducing the pre-change behaviour, and SHALL be declared on the
configuration model rather than at any runner call site.

#### Scenario: Three attempts retain three distinct records

- WHEN k is 3
- THEN the result store contains attempts 1, 2 and 3 with distinct attempt IDs
- AND no attempt overwrites another attempt

#### Scenario: The default reproduces existing behaviour

- WHEN no attempt count is configured
- THEN each item runs exactly once
- AND the emitted result is byte-identical to the pre-change output

### Requirement: Attempts are real, independent invocations the harness does not perturb

The system SHALL execute each attempt as a separate `target.run` invocation through the full
scorer lifecycle, and SHALL NOT introduce any variation of its own between attempts. All observed
variation must originate in the target's own sampling; harness-injected variance would measure the
harness rather than the agent.

> Supersedes an earlier "Attempts are independently seeded" requirement, which was based on a
> false premise. `Target.run(self, item)` receives only the item — the per-item RNG goes to
> scorers via `RunContext`, never to the target — so re-seeding cannot change a target's output.

#### Scenario: k attempts are k invocations, not one result copied

- WHEN an item runs with k of 5
- THEN the target is invoked exactly five times for that item
- AND no caching or memoisation between the engine and the target collapses the five into one

#### Scenario: The harness does not manufacture variation

- WHEN an item runs with k greater than 1
- THEN every attempt passes byte-identical input to the target
- AND no seed, prompt or sampling parameter differs across the attempts of one item

### Requirement: pass^k measures target reliability, not scorer noise

`RunContext.rng` is a mutable `random.Random` handed to scorers. Reusing one instance across
attempts lets a scorer's draws advance it, so attempt 2 can reach a different verdict than
attempt 1 for *identical* target output — harness-side variance counted as agent unreliability.
The system SHALL therefore reset the scorer RNG to the item's seed at the start of each attempt,
so that every difference between attempts is attributable to the target.

Scorer randomness is deliberately **excluded** from this metric rather than included: a
judge-scorer's sampling noise and an agent's flakiness are different failures, and a single
scalar that mixes them cannot be acted on.

#### Scenario: A randomised scorer does not make a deterministic target look unreliable

- WHEN a deterministic target runs with k of 5 and a scorer that draws from `ctx.rng`
- THEN all five attempts receive the same scorer random stream
- AND `pass^k` is 1.0, because the target's behaviour did not vary

### Requirement: A structurally uninformative pass^k is reported as such

When the configuration makes repeated attempts identical by construction, the system SHALL emit a
diagnostic alongside the metric. The value itself is correct — a deterministic agent *is*
perfectly reliable under that configuration — but read without the diagnostic it is mistaken for
evidence of robustness. This is the failure ADR 0029 records: a metric reporting a pass having
measured nothing.

**Detection** is by declaration first, observation second — never by guessing at a target's
internals:

1. A target MAY declare itself deterministic via an optional `is_deterministic` property on the
   `TargetRunner` protocol. Absent (the default for every existing target), it is unknown, not
   `False` — an added optional member keeps the protocol backward compatible (ADR 0031
   obligation 1).
2. `ModelTarget` derives it: `temperature == 0.0` (or `top_p == 0`) ⇒ deterministic. Fixture and
   replay targets declare it directly, since they return recorded output by construction.
3. When neither applies, the run observes: if all k attempts produced byte-identical
   `TargetOutput.output`, the metric is uninformative *in this run* regardless of why.

**Emitted shape.** The diagnostic is a run-level field, not free text parsed out of a log:
`reliability.diagnostics` is a list of `{code, message}` objects, with
`code = "deterministic_sampling"` for this case. It is emitted **only** when `pass^k == 1.0` and
one of the three detections holds, so a genuinely reliable non-deterministic agent is not
annotated. The key is omitted entirely when the list is empty, keeping pre-change result JSON
byte-identical.

#### Scenario: A deterministic configuration is flagged, not silently passed

- WHEN a target configured with `temperature=0` (or a fixture/replay target) runs with k of 5
- THEN `pass^k` is reported as 1.0
- AND `reliability.diagnostics` contains one entry with code `deterministic_sampling`
- AND its message states that the value follows from deterministic sampling, not from measured
  agent reliability

#### Scenario: A genuinely reliable sampling agent is not annotated

- WHEN a target with `temperature=0.7` runs with k of 5 and every attempt passes
- THEN `pass^k` is reported as 1.0
- AND no `deterministic_sampling` diagnostic is emitted, because the agent was actually measured

#### Scenario: Attempt expansion does not trip the duplicate-item guard

- WHEN k is greater than 1
- THEN the duplicate-item-ID check still evaluates the dataset exactly once
- AND no duplicate-ID warning is emitted for attempts of the same item

### Requirement: Reliability includes pass@k and pass^k

For each evaluation item, the system SHALL report `pass@k` as true when at least one of the k
attempts passes, and `pass^k` as true only when every one of the k attempts passes.

Both SHALL be aggregated per evaluation item and SHALL NOT be pooled across unrelated items.

#### Scenario: One of three attempts succeeds

- WHEN the attempt outcomes are fail, pass, fail
- THEN `pass@3` is true
- AND `pass^3` is false

#### Scenario: Every attempt succeeds

- WHEN all k attempts pass
- THEN both `pass@k` and `pass^k` are true

#### Scenario: Per-item reliability is not averaged away

- WHEN one item passes all k attempts and another passes none
- THEN each item reports its own `pass^k`
- AND the run-level summary does not present a single pooled `pass^k` as if it were a per-item result

### Requirement: Reliability reports distributions

The system SHALL retain and report the distribution of scores, latency, usage, cost, step count and
failure categories across attempts.

#### Scenario: Aggregate output does not hide variance

- WHEN two attempts pass quickly and one times out
- THEN the report includes the timeout
- AND reports the latency distribution rather than only the successful mean

#### Scenario: Raw attempts are persisted before aggregation

- WHEN aggregates are computed
- THEN every raw attempt record already exists in the result payload
- AND the aggregation is a pure function of those records

### Requirement: Reliability metrics can gate a run

The system SHALL allow a gate rule to threshold `pass_at_k` and `pass_power_k` using the existing
gate rule model.

#### Scenario: A reliability gate uses the existing rule shape

- WHEN a gate rule names metric `pass_power_k` with a minimum
- THEN it is validated by the same configuration model as `mean` and `pass_rate` rules
- AND a configuration that introduces an unknown top-level gate key is rejected at parse time
