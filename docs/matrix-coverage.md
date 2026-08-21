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
| `regex_match` | 2 | 1 | 1 | 1 | 1 |
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
| engine | M8 | M8×6 |
| gating | M1, M2, M6 | M1×2, M2×2, M6×4 |

## M8 pipelines — kinds exercised

| kind | canonical components exercised in ≥1 pipeline |
|---|---|
| dataset | `inline` |
| judge | `mock` |
| scorer | `contains`, `exact_match`, `llm_judge`, `trajectory_any_order`, `trajectory_exact`, `trajectory_in_order`, `trajectory_loop_detection`, `trajectory_precision_recall`, `trajectory_recovery`, `trajectory_step_efficiency`, `weighted` |
| sink | `console`, `json_file` |
| target | `callable`, `echo` |

## Follow-on obligations (queued OpenSpec changes)

Self-guarded: a row whose component appears in the census fails the guard as
"satisfied — remove the row".

| change | note |
|---|---|
| `add-stateful-outcome-evaluation` | STATE_ADAPTERS is a sixth registry: the census discovers it automatically and this guard fails until it has a REQUIRED_DIMS row plus rows for the four local adapters and the two state scorers (whose registered names must also land in both READMEs for the registry-drift guard). |
