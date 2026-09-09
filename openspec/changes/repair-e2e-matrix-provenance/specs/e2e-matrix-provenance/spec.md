# Spec delta: e2e-matrix-provenance

Capability: the committed e2e-matrix artifact's Provenance SHA is gated as reachable
(ancestor of HEAD), and a render may not drop evidence counts without a waiver.

## ADDED Requirements

### Requirement: Provenance SHA is reachable, not equal to HEAD

The system SHALL accept a Provenance Commit SHA that exists and is an ancestor of HEAD,
and SHALL NOT require that SHA to equal HEAD.

#### Scenario: A SHA that is not an ancestor fails

- WHEN `--check` runs against an artifact whose Commit SHA exists but is not an ancestor
  of HEAD
- AND that SHA is not in `PROVENANCE_SHA_WAIVERS`
- THEN the check exits non-zero naming the SHA

#### Scenario: A shallow clone does not fail closed on a missing object

- WHEN the SHA is absent from the local object store
- THEN the ancestor check is skipped rather than failed

### Requirement: A render that drops evidence carries a waiver

The system SHALL refuse `--update` when observed-step count or a Coverage Grid suite test
count drops, unless `MONOTONICITY_WAIVERS` contains that exact (metric, previous, current)
triple.

#### Scenario: The ERRATA 1627→995 drop is waived and only that pair

- WHEN previous suite:root tests are 1627 and current are 995
- THEN the monotonicity gate accepts the drop
- WHEN a different drop (for example 1627→100) is proposed
- THEN the gate fails
