---
name: eval-corpus-forge
description: 'Build, validate, and package reusable evaluation datasets for agent and LLM systems from prompts, traces, tool-call logs, metadata, and expected outcomes. Use this when the user asks to gather eval data, create benchmark datasets, normalize traces, define reusable ground truth, bootstrap eval suites, or produce retrieval, tool-invocation, response, or end-to-end evaluation artifacts.'
validator_version: '2.0'
compatibility: python>=3.10
version: 1.0.0
---

# Eval Corpus Forge

Perform evaluation dataset gathering and packaging end to end: take raw prompts, execution
traces, tool-call logs, metadata, and expected outcomes; normalize them into canonical
scenario records; generate reusable ground-truth mappings and eval-suite views; validate the
resulting package; and — because this task produces verifiable artifacts — prove it passed
validation before reporting success (§7 and §8).

One reusable dataset can support multiple evaluation suites: retrieval accuracy, tool
correctness, response/output quality, and end-to-end task completion. Full schemas live in
`references/schemas.md`; this body is the procedure and contract.

## 1. Preconditions

Confirm before executing. If any fails, stop and report the exact missing requirement and
fix. Do not fabricate missing data.

* A source input exists: a `.json`, `.jsonl`, or `.csv` file, a conversation transcript
  (a JSON/JSONL object with a `messages`/`turns` array), or a folder mixing these. CSV rows
  become one scenario each (JSON-encoded cells are parsed); transcripts expand into one
  scenario per user turn, pairing the following assistant turn for response and tool names.
  Trace-export formats beyond the transcript shape are out of scope.
* The input includes at least one prompt or scenario, and at least one expected outcome,
  evaluation target, or ground-truth artifact. If no prompts or scenarios are discoverable,
  stop.
* Python 3.10+ is available; write access exists for the output's parent directory; bundled
  scripts under `scripts/` are present.

### Mode selection

* **Full dataset mode** — when any record carries an observable execution artifact (tool
  call, trace step, retrieved entity/ID, model response, or workflow-completion record).
  Tool/retrieval/response/e2e views are populated only where the matching evidence exists.
* **Bootstrap mode** — when only prompts, scenarios, or expected outcomes are available.
  Generate only applicable views; mark the rest not-applicable in `manifest.json`. Never
  fabricate tool traces, retrieval results, token usage, latency, model outputs, or
  workflow-completion records.

## 2. Output package contract

```text
<output>/
  manifest.json
  canonical/scenarios.jsonl
  ground_truth/mappings.jsonl
  views/{retrieval_eval,tool_invocation_eval,response_eval,end_to_end_eval}.jsonl
  validation/{validation_report.json,schema_errors.jsonl}
  provenance/source_index.jsonl
```

All JSONL is UTF-8, one JSON object per line. All view files are always created; a
non-applicable view is left empty with its reason recorded in `manifest.json`. Do not write
placeholder records, and do not duplicate canonical records inside derived views.

## 3. Schemas

See `references/schemas.md` for the canonical scenario, deterministic `scenario_id`,
`provenance`, `trace`, `metadata`, ground-truth mapping, and per-view evidence requirements.
Key rule: missing values are represented as `null`, empty array, or `"unclassified"` — never
omitted.

## 4. Procedure

Deterministic and reproducible. Delegate mechanical work to the bundled scripts.

```bash
python scripts/run_eval_corpus_forge.py --in <input> --out <output>
python scripts/validate_skill.py --skill . --tier structural,behavioral
```

The runner executes §5's pipeline; you normally invoke it directly rather than redoing steps
by hand.

## 5. Pipeline

1. **Ingest** — discover/parse records, preserve origin for provenance, detect mode, confirm
   minimum data. Stop if no prompts or scenarios are discoverable.
2. **Normalize** — convert each record to the canonical scenario schema; generate
   deterministic `scenario_id` when missing; preserve source ids and provenance.
3. **Extract trace** — capture tool names/order/arguments/outputs, retrieved entities/ids,
   model metadata, token usage, latency, trace ids where present; null/empty otherwise. Never
   invent trace data.
4. **Enrich metadata** — complexity, taxonomy tags, expected action types, evaluator
   applicability. Explicit when the source provides it, else `unclassified` (no silent
   inference in v1).
5. **Build ground truth** — expected entities/output fields/tools/sequence/completion/final
   state/grading notes, stored separately and referencing canonical `scenario_id`.
6. **Generate views** — retrieval, tool-invocation, response, end-to-end. Emit a record only
   with the required evidence; otherwise leave the view empty and record the reason.
7. **Atomic write** — write to a sibling `<output>.tmp.<ts>`, validate it, and only on pass
   move any existing output to `<output>.bak.<ts>` and swap the temp into place. On failure,
   leave the original untouched and preserve the temp for debugging.

## 6. Manifest

`manifest.json` carries `dataset_name`, `created_at`, `source_input`, `schema_version`,
`mode`, programmatic `counts`, `view_applicability` (per view `{applicable, reason}`), and
`validation` (`status`, `report_path`). Counts are computed by the pipeline and independently
re-counted from disk by validation — they are never estimated by hand.

## 7. Validation

Run structural and behavioral validation before reporting success.

* **Structural** fails on: no canonical scenarios; missing required fields; omitted (vs.
  null/empty/`unclassified`) values; a view referencing a missing `scenario_id`; manifest
  counts not matching disk; ground-truth referencing missing scenarios; applicability that
  contradicts the data; missing validation artifacts; a view record lacking its required
  evidence.
* **Behavioral** confirms: `scenario_id` is stable/deterministic; each view record maps to
  exactly one canonical scenario; ground truth is separate from canonical; views do not
  duplicate full canonical records; tool invocation order is preserved; provenance is
  traceable; empty views are labeled not-applicable; bootstrap mode fabricates nothing.

The skill is **not done** until this exits 0:

```bash
python scripts/validate_skill.py --skill . --tier structural,behavioral
```

## 8. Reporting

Report success only if validation passed, using counts from the manifest and pointing at
`validation/validation_report.json` as evidence. Include a `Not applicable views:` section
only when at least one view is not applicable. On failure, report that validation failed, the
report path, the failed checks, that the original output was preserved, and the required
fixes — never an unsupported count or inferred success.

## 9. Examples

* **Full dataset** — `--in` a folder of JSONL records with prompts + traces + tool calls +
  expected outputs ⇒ all four views populated, validation passed.
* **Bootstrap** — `--in` prompts + expected outcomes only ⇒ retrieval/tool/response views
  empty and labeled not-applicable; end-to-end populated from the success targets.
* **No prompts** — `--in` records with metadata but no prompt/scenario ⇒ stops with
  `no prompts or scenarios`, no package written.
