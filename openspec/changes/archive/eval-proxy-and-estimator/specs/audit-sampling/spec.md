# Spec delta: audit-sampling

Capability: the unbiased audit sampler and the outcome record it writes.
Compiles down to F-IDs in `features.yaml` (claimed at land) + `scripts/validations/F_0NN.py`.

## MODIFIED Requirements

### Requirement: Audit records carry their selection propensity

The audit sampler SHALL record, on each HUMAN_AUDIT outcome record, the known marginal
probability with which that change was selected for audit
(`p = min(1, k/N) + (1 − min(1, k/N)) · base_rate`, where `k` is the per-domain floor need and
`N` the domain's candidate count). The propensity field SHALL be optional and nullable so that
records written before this change, and by older writers, continue to load unchanged. Storing
the propensity SHALL NOT change which records are selected (selection stays content-blind and
unbiased) and SHALL NOT change any gate decision; it exists to enable Horvitz–Thompson /
prediction-powered weighting and any future non-uniform sampling.

#### Scenario: A newly audited record stores a valid propensity

- **WHEN** `select_for_audit` picks a change and `record_verdict` writes its HUMAN_AUDIT record
- **THEN** the record's `selection_propensity` is a value in `(0, 1]` equal to that change's
  marginal inclusion probability for the round

#### Scenario: Older records remain readable

- **WHEN** the store contains records written before the propensity field existed (no such key)
- **THEN** they load successfully with `selection_propensity` defaulting to null, and no reader
  raises (consistent with the unknown/missing-field tolerance of ADR 0025)

#### Scenario: Selection remains unbiased

- **WHEN** propensity logging is enabled
- **THEN** the set of change_ids `select_for_audit` returns is identical to the pre-change
  sampler for the same store and RNG seed (content-blind selection is unchanged)
