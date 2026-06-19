# eval-corpus-forge — schemas reference

Detailed schemas for the package artifacts. The SKILL.md body links here to stay concise.

## Canonical scenario (`canonical/scenarios.jsonl`)

```json
{
  "scenario_id": "string",
  "session_id": "string|null",
  "turn_id": "string|null",
  "raw_prompt": "string",
  "task_context": "string|null",
  "expected_intent": "string|null",
  "expected_outcome": "object|null",
  "provenance": "object",
  "trace": "object|null",
  "metadata": "object"
}
```

Missing values are represented as `null`, empty array, or `"unclassified"` — never omitted.

### Deterministic `scenario_id`

When the source omits `scenario_id`, it is generated as `scn_<sha256[:16]>` over the
`\x1f`-joined tuple `[source_file, locator, session_id, turn_id, normalized_prompt]` where
`normalized_prompt` is whitespace-collapsed and lowercased. Identical input ⇒ identical id
across runs. Source-provided ids are preserved verbatim (and are not re-checked for
determinism).

### `provenance`

```json
{ "source_file": "string", "locator": "string|int", "session_id": "string|null", "turn_id": "string|null" }
```

`locator` is a stable within-file position: JSONL line number, JSON-array index, or `"0"`
for a single object.

### `trace` (present only when execution data exists; all fields included when present)

```json
{
  "tool_names": ["string"],
  "tool_invocation_order": ["string"],
  "tool_arguments": ["object"],
  "tool_outputs": ["object"],
  "retrieved_entities": ["object"],
  "retrieved_ids": ["string"],
  "model_name": "string|null",
  "token_usage": "object|null",
  "latency_ms": "number|null",
  "trace_ids": ["string"]
}
```

### `metadata`

```json
{
  "complexity": "low|medium|high|unclassified",
  "complexity_source": "explicit|inferred|unclassified",
  "taxonomy_tags": ["string"],
  "taxonomy_source": "explicit|inferred|unclassified",
  "expected_action_types": ["retrieve|call_tool|respond|complete_workflow|unclassified"],
  "evaluator_applicability": { "retrieval": true, "tool_invocation": true, "response": true, "end_to_end": true }
}
```

**v1 has no silent inference engine.** `complexity` and `taxonomy_tags` are `explicit` when
the source provides them, else `unclassified`. The `inferred` source value is reserved and
unused in v1. `expected_action_types` is derived strictly from present evidence (trace tools
⇒ `call_tool`, retrieval data ⇒ `retrieve`, response ⇒ `respond`, completion ⇒
`complete_workflow`); absent any, `["unclassified"]`. `evaluator_applicability` flags use the
same evidence predicates as the views and may not contradict whether the scenario
contributed to the corresponding view.

## Ground-truth mapping (`ground_truth/mappings.jsonl`)

```json
{
  "scenario_id": "string",
  "expected_entities": ["object"],
  "expected_output_fields": "object|null",
  "expected_tools": ["string"],
  "expected_tool_sequence": ["string"],
  "expected_workflow_completion_status": "string|null",
  "expected_final_state": "object|null",
  "grading_notes": "string|null",
  "provenance": "object"
}
```

References a valid `scenario_id`, never duplicates canonical scenario data (no `raw_prompt`),
and only carries fields the source explicitly supports.

## Derived views (`views/*.jsonl`)

Each record is a thin projection referencing `scenario_id` — never the full canonical record.
A scenario contributes to a view only with the required evidence:

| view | required evidence |
|------|-------------------|
| `retrieval_eval` | retrieved ids or entities |
| `tool_invocation_eval` | tool-call data (invocation order preserved) |
| `response_eval` | a response artifact **and** a comparison target (`expected_output_fields` or `rubric`) — `expected_outcome` alone does **not** qualify |
| `end_to_end_eval` | a scenario-level success target / expected final state |

If zero records qualify, the file is empty and `manifest.view_applicability[view]` records
`{ "applicable": false, "reason": "…" }`.
