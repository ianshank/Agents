<!-- GENERATED FILE - do not edit by hand.
     Regenerate: python tests/test_matrix_coverage.py --update
     Freshness-gated by tests/test_matrix_coverage.py::test_matrix_doc_is_fresh. -->

# Evaluation test matrix — coverage

Component × dimension coverage of `tests/test_matrix_eval_tools.py`, derived from
the live registries (fresh-subprocess census) and the AST cell map. Cells are
static `test_m<dim>_*` method counts; `waived` cells carry their reason below each
table. Policy (dim floors, waiver rules): ADR 0032; enforcement:
`tests/test_matrix_coverage.py`.

Dimensions: M1 Correctness · M2 Edge Cases · M3 Type Safety · M4 Interface · M5 Determinism · M6 Error Handling · M7 Registry · M8 Composability.
M4 and M7 are global-dynamic (parametrized over the live registries and the
committed baseline); M8 is per-kind (see the pipelines section).

## dataset (floor: M1, M2, M3, M6)

| component | M1 | M2 | M3 | M5 | M6 |
|---|---|---|---|---|---|
| `braintrust` | 1 | 1 | 1 | — | 1 |
| `csv` | 1 | 1 | 1 | — | 1 |
| `inline` | 1 | 1 | 1 | — | waived |
| `jsonl` | 1 | 1 | 1 | — | 1 |
| `langfuse` | 1 | 1 | 1 | — | 1 |
| `parquet` | 1 | 1 | 1 | — | 2 |

- `inline` M6 waived: config-embedded items have no I/O failure path; a malformed record fails loudly at load

Aliases (dataset):

| alias | canonical |
|---|---|
| `csv_file` | `csv` |
| `parquet_file` | `parquet` |

## judge (floor: M1, M2, M3, M6)

| component | M1 | M2 | M3 | M5 | M6 |
|---|---|---|---|---|---|
| `anthropic` | 1 | 1 | 1 | — | 1 |
| `bedrock` | 1 | 1 | 1 | — | 1 |
| `mock` | 3 | 2 | 1 | 1 | 1 |
| `openai` | 1 | 1 | 1 | — | 1 |
| `panel` | 3 | 3 | 1 | 1 | 3 |
| `phoenix_evals` | 1 | 1 | 1 | — | 1 |

Aliases (judge):

| alias | canonical |
|---|---|
| `claude` | `anthropic` |
| `deterministic` | `mock` |
| `phoenix-evals` | `phoenix_evals` |

## scorer (floor: M1, M2, M3, M5, M6)

| component | M1 | M2 | M3 | M5 | M6 |
|---|---|---|---|---|---|
| `autoevals` | 2 | 1 | 1 | 1 | 2 |
| `contains` | 4 | 2 | 1 | 1 | 1 |
| `exact_match` | 4 | 3 | 1 | 1 | 1 |
| `json_keys` | 3 | 3 | 1 | 1 | 1 |
| `llm_judge` | 3 | 1 | 1 | 1 | 1 |
| `policy_violation` | 3 | 2 | 1 | 1 | 1 |
| `regex_match` | 2 | 1 | 1 | 1 | 1 |
| `state_transition` | 4 | 3 | 2 | 1 | 1 |
| `trajectory_any_order` | 2 | 5 | 1 | 1 | 1 |
| `trajectory_exact` | 2 | 5 | 1 | 1 | 1 |
| `trajectory_in_order` | 2 | 5 | 1 | 1 | 1 |
| `trajectory_loop_detection` | 2 | 5 | 1 | 1 | 1 |
| `trajectory_precision_recall` | 2 | 5 | 1 | 1 | 1 |
| `trajectory_recovery` | 3 | 5 | 1 | 1 | 1 |
| `trajectory_step_efficiency` | 3 | 5 | 1 | 1 | 1 |
| `weighted` | 2 | 1 | 1 | 1 | 3 |

Aliases (scorer):

| alias | canonical |
|---|---|
| `composite` | `weighted` |
| `ensemble` | `weighted` |
| `exact` | `exact_match` |
| `judge` | `llm_judge` |
| `llm-judge` | `llm_judge` |
| `regex` | `regex_match` |
| `schema_keys` | `json_keys` |
| `trajectory-any-order` | `trajectory_any_order` |
| `trajectory-exact` | `trajectory_exact` |
| `trajectory-in-order` | `trajectory_in_order` |
| `trajectory-loop-detection` | `trajectory_loop_detection` |
| `trajectory-precision-recall` | `trajectory_precision_recall` |
| `trajectory-recovery` | `trajectory_recovery` |
| `trajectory-step-efficiency` | `trajectory_step_efficiency` |

## sink (floor: M1, M2, M6)

| component | M1 | M2 | M3 | M5 | M6 |
|---|---|---|---|---|---|
| `braintrust` | 1 | 1 | — | — | 1 |
| `console` | 2 | 1 | 1 | — | waived |
| `html_file` | 2 | 1 | 1 | 1 | 1 |
| `json_file` | 1 | 1 | 1 | 1 | 1 |
| `langfuse` | 1 | 1 | — | — | 1 |
| `phoenix` | 2 | 1 | — | — | 1 |

- `console` M6 waived: prints to stdout; no failure path to exercise

Aliases (sink):

| alias | canonical |
|---|---|
| `html` | `html_file` |
| `json` | `json_file` |

## state_adapter (floor: M1, M2, M3, M5, M6)

| component | M1 | M2 | M3 | M5 | M6 |
|---|---|---|---|---|---|
| `filesystem` | 3 | 4 | 1 | 1 | 2 |
| `in_memory` | 3 | 3 | 1 | 1 | 3 |
| `mock_http` | 5 | 3 | 1 | 1 | 3 |
| `sqlite` | 4 | 4 | 1 | 1 | 2 |

## target (floor: M1, M2, M3, M6)

| component | M1 | M2 | M3 | M5 | M6 |
|---|---|---|---|---|---|
| `callable` | 1 | 1 | 1 | — | 1 |
| `echo` | 2 | 1 | 1 | 1 | waived |
| `model` | 1 | 1 | 1 | — | 2 |

- `echo` M6 waived: no failure modes by design (pure dict access)

Aliases (target):

| alias | canonical |
|---|---|
| `llm` | `model` |
| `python` | `callable` |

## Extra suites (non-registry rows)

| suite | floor | dims covered (method counts) |
|---|---|---|
| engine | M8 | M8×23 |
| gating | M1, M2, M6 | M1×2, M2×2, M6×4 |

## M8 pipelines — kinds exercised

Every component below is **execution-verified**, not merely declared: each M8
pipeline runs inside `tests/_m8_probe.py`'s ledger, and
`_assert_declared_components_ran` fails the pipeline if it names a component
whose protocol method never ran. The check is per pipeline, not a repo-wide
union — a union would credit a component here because some *other* pipeline
invoked it, which is the vacuous credit the ledger exists to refuse.

| kind | canonical components exercised in ≥1 pipeline |
|---|---|
| dataset | `braintrust`, `csv`, `inline`, `jsonl`, `langfuse`, `parquet` |
| judge | `anthropic`, `mock`, `openai`, `panel` |
| scorer | `autoevals`, `contains`, `exact_match`, `json_keys`, `llm_judge`, `policy_violation`, `regex_match`, `state_transition`, `trajectory_any_order`, `trajectory_exact`, `trajectory_in_order`, `trajectory_loop_detection`, `trajectory_precision_recall`, `trajectory_recovery`, `trajectory_step_efficiency`, `weighted` |
| sink | `braintrust`, `console`, `html_file`, `json_file`, `langfuse`, `phoenix` |
| state_adapter | `filesystem`, `in_memory`, `mock_http`, `sqlite` |
| target | `callable`, `echo`, `model` |

Waived M8 cells — infeasible in the matrix CI job, with the reason. Named here
rather than left absent: a component missing from the table above with no
explanation is indistinguishable from one nobody considered.

- `judge/bedrock`: boto3 is absent from eval-harness-ci.yml's install line
- `judge/phoenix_evals`: arize-phoenix-evals is absent from eval-harness-ci.yml's install line and has no _EXTRA_PROVIDES entry; its pandas/numpy footprint against the pyarrow>=14,<20 pin is an open question phoenix-live.yml's dep-resolve job should answer first

## Follow-on obligations (queued OpenSpec changes)

Self-guarded: a row whose component appears in the census fails the guard as
"satisfied — remove the row".

| change | note |
|---|---|
