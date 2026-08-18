# Design: add-eval-matrix-completeness

Promotes to [ADR 0032](../../../../docs/decisions/0032-matrix-completeness-policy.md) (authored
with this proposal as *Proposed*; flipped to Accepted at land). The normative policy — the
per-kind dim floors, the waiver rules, the checked-declaration principle — lives in the ADR;
this file records the mechanism trade-offs.

## Where the guard lives: a pytest suite, not a `scripts/` gate

A `scripts/check_matrix_coverage.py` gate would need the full registration sweep a new gate
script carries — a `run:` line in `quality-gates.yml`, an entry in
`check_charter_invariants._EXPECTED_GATE_SCRIPTS`, and membership in the tooling-coverage
step's pytest and `--cov=` lists. A pytest suite in `tests/` is auto-discovered
(`testpaths = ["tests"]`), runs on all three Pythons via `eval-harness-ci.yml → make check`,
and needs none of that. The only registration it does need is the F-ID proof
(`scripts/validations/F_053.py`), which follows the existing validator pattern.

## Census: a fresh subprocess, with a richer payload than the surface guard's

The registries are process-global and two test modules register doubles into them
(`tests/test_plugin_registry_surface.py:12-16` records this), so an in-process census is
collection-order-dependent. The probe is the surface guard's pattern — same sys.path
preamble, timeout, exit/garbled failure handling — but its payload is
`{kind: {"names": [...], "aliases": {alias: canonical}}}`, **not** the flat
`sorted(names | aliases)` union: a verbatim clone would demand matrix rows for all 23 aliases.
Registries are discovered dynamically (`isinstance(obj, Registry)` over
`eval_harness.plugins`, keyed by `.kind`), so `add-stateful-outcome-evaluation`'s
`STATE_ADAPTERS` is censused the day it lands and fails the guard with an actionable message
(add a `REQUIRED_DIMS` row, amend ADR 0032, add waivers if needed, regenerate the doc) until
its rows exist. One probe result is cached per process — the suite runs up to six times per
PR (two pytest passes per Python × three Pythons), and the census must not multiply that.

## Cell map: AST over `tests/test_matrix_*.py`, with checked declarations

Runtime introspection (collect the suite, read markers) cannot reach the Phase-2 sibling
suites — they are not importable from the root environment and the airgap forbids making them
so. AST parsing works uniformly across both phases with one extractor. Each per-component
class carries two literal class attributes:

```python
class TestTrajectoryExactScorer:
    MATRIX_KIND = "scorer"
    MATRIX_COMPONENTS = ("trajectory_exact",)
```

Dims are the union of `test_m([1-8])_` method-name matches; per-cell counts are static method
counts, never runtime-parametrized case counts. The apparent contradiction with this change's
own anti-hardcoding thesis dissolves under the principle ADR 0032 records: *a literal is
banned where it claims completeness unchecked (the old M7 lists); a literal cross-checked
against the live census is a checked declaration* — a stale `MATRIX_COMPONENTS` tuple fails
the both-directions check exactly like a stale waiver. Global classes (`TestM4Interface`,
`TestM7Registry`, `TestM8Composability`) are an explicit allowlist; any other class with
`test_mN_` methods and no `MATRIX_KIND` fails as an unmapped matrix class.

## M8: an importable `PIPELINES` constant, not AST mining

Extracting `"type"` string literals from M8 dict literals cannot work: the name→kind mapping
is not injective (`braintrust` and `langfuse` are registered in both DATASETS and SINKS), and
reconstructing the enclosing config path from nested AST breaks on the first refactor.
Instead `tests/test_matrix_eval_tools.py` exports `PIPELINES: dict[str, dict]`; the M8 tests
parametrize over it and *run* the configs; the guard **imports** it (the root matrix file is
importable in-process — only sibling files are not) and reads component kinds from
`EvalConfig.model_validate(cfg)` typed fields. Every censused kind, judges included, must
appear in at least one pipeline.

## The alias-pairing freeze

Deleting the hardcoded M7 pairs would demote a hard CI guarantee ("`judge` resolves to
`llm_judge`") to a rendered table a reviewer must notice, because the committed registry
baseline stores names and aliases merged flat and `Registry._aliases` assignment has no
duplicate guard — an alias can be silently repointed and still *resolve*. The guard therefore
asserts per kind `dict(census aliases) == FROZEN_ALIAS_MAP[kind]` by exact equality, with the
frozen map single-sourced in `tests/_matrix_coverage.py`. The artifact's alias table stays as
the human-readable view of the same data.

## No per-cell baseline JSON

The policy floor is asserted live against the census and the AST cell map; the committed,
freshness-gated `docs/matrix-coverage.md` already **is** the reviewable full-grid snapshot. A
`matrix_coverage_baseline.json` would duplicate that information and add `--update` churn on
every test addition. The refuse-drop property is inherent: deleting a required cell fails the
policy assertion directly.

## Ledger conventions (recorded here because they deviate from recent habit)

- **`implemented_in` derivation.** The F-053 entry lands `status: in_progress` in the commit
  that adds the ledger entry and the proof together, and a later commit in the same PR flips
  it to `done` with `implemented_in` set to that earlier commit's SHA — the commit that added
  BOTH the entry and `F_053.py`, which is exactly the derivation rule `ae1cfc6` recorded,
  made possible without self-reference. Merge commits are kept; squash-merging rots the ref.
- **Archival is a post-merge follow-up**, stamped with the real merge SHA — matching how
  `ae1cfc6` archived the previous four changes, rather than inventing a same-PR convention
  with an undefined stamp.

## Scope boundary (also in ADR 0032)

`experiments/backend-validation` (temporary, own quality gate, deliberately outside
`make check-all`), `demo/`, and `examples/` are outside the matrix. The skills layer and the
five sibling packages are `extend-matrix-to-fleet`'s scope.
