# Spec delta: fleet-matrix-census

Capability: sibling packages participate in the matrix convention via a derived or
checked-declaration census, cross-checked against each package's frozen public surface.

## ADDED Requirements

### Requirement: Derived censuses exclude false-friend containers

The system SHALL derive agent-core calibrator names from `CALIBRATOR_FACTORIES` and SHALL
NOT treat `CalibratorRegistry` as a factory name.

#### Scenario: CalibratorRegistry is not in the derived set

- WHEN the fleet census for agent-core is computed
- THEN the names are the factory keys (`isotonic`, `temperature`)
- AND `CalibratorRegistry` is absent

### Requirement: Hand declarations are a subset of the frozen surface

The system SHALL fail when a hand-declared fleet component is not an exported name in that
package's public-surface or backwards-compat baseline.

#### Scenario: An invented declaration fails

- WHEN a package declares a name that the baseline does not export
- THEN `fleet_problems` names that component
