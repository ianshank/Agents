# Spec delta: eval-matrix

Capability: the evaluation test matrix — every registered component × the standardized metric
dimensions — is complete for the root harness, and completeness is machine-enforced rather
than hand-maintained.

## ADDED Requirements

### Requirement: Every registered component has matrix rows meeting a per-kind floor

The system SHALL derive the set of components that require matrix coverage from the live
component registries (never from a hand-maintained list), and SHALL fail when any registered
component lacks test rows for its kind's required dimensions, as declared in a single policy
table. A cell may be waived only with a recorded reason.

#### Scenario: A newly registered component fails until it has rows

- WHEN a component is registered in any registry and no matrix class declares it
- THEN the completeness guard fails, naming the component and its kind

#### Scenario: A new registry kind fails until it has a policy row

- WHEN a sixth registry is added to `eval_harness.plugins`
- THEN the guard discovers it without a code change to the census
- AND fails with an actionable message until the policy table carries a row for the new kind

#### Scenario: Waivers cannot go stale in either direction

- WHEN a waiver names a component that is no longer registered
- THEN the guard fails ("stale waiver")
- WHEN a waived cell gains real tests
- THEN the guard fails ("waiver no longer needed")

### Requirement: Matrix declarations are checked, not trusted

Per-component matrix classes SHALL declare their kind and components as literal attributes,
and the guard SHALL cross-check every declaration against the census in both directions: a
class claiming an unregistered component fails, and a matrix-dimension test method outside a
declared or allowlisted class fails.

#### Scenario: A stale declaration is caught

- WHEN a matrix class declares a component name that no registry knows
- THEN the guard fails, naming the class and the unknown component

### Requirement: Registry keys and alias pairings are asserted, not rendered only

The system SHALL assert that every committed registry-surface key resolves in the live
registry of its kind, and SHALL assert the alias→canonical mapping per kind by exact
equality against a frozen map — a repointed alias is a CI failure, not a document diff.

#### Scenario: A repointed alias fails

- WHEN an alias is re-registered against a different canonical name
- THEN the alias-map assertion fails even though the alias still resolves

### Requirement: The trajectory scorers are first-class matrix rows

All seven trajectory scorers SHALL have matrix rows for their kind's required dimensions,
including one engine pipeline built from a shipped trajectory-emitting callable target whose
gate PASSES.

#### Scenario: The shipped example is a working example

- WHEN the shipped trajectory example configuration runs end to end
- THEN its own gate passes
- AND the emitted payload contains the trajectory in execution order

### Requirement: The matrix has a generated, freshness-gated artifact

The system SHALL render the full coverage grid — components × dimensions with per-cell test
counts, waived cells with reasons, alias tables, and recorded follow-on obligations — into a
committed document generated deterministically from the census and the test files, and SHALL
fail CI when the committed document does not match a regeneration.

#### Scenario: A hand edit to the generated document fails

- WHEN the committed document differs from an in-memory regeneration
- THEN the freshness check fails and names the regeneration command

#### Scenario: A satisfied follow-on obligation must be retired

- WHEN a recorded follow-on obligation names a component that now exists in the census
- THEN the guard fails ("satisfied — remove the row")
