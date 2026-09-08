---
name: update-executive-report
description: Update and regenerate the evaluation tools executive report, comparative metrics, and visual presentation charts. Use this whenever the user asks to update the executive report, refresh eval tool metrics, or re-run evaluation visualization after benchmark changes.
---

# Update Executive Report — E2E Action Skill

Perform the update and maintenance of the LLM Evaluation Tools Executive Report ([`docs/executive-report-eval-tools.md`](../../../docs/executive-report-eval-tools.md)) and its companion visual metrics chart ([`docs/eval_metrics_comparison.png`](../../../docs/eval_metrics_comparison.png)).

## 1. Preconditions (Input Contract)

Confirm these hold before proceeding:

- The schema definition exists at [`docs/eval_metrics_schema.json`](../../../docs/eval_metrics_schema.json).
- The current metrics dataset exists at [`docs/eval_metrics.json`](../../../docs/eval_metrics.json).
- The generator script exists at [`scripts/generate_eval_metrics.py`](../../../scripts/generate_eval_metrics.py).
- Python environment has `matplotlib` and `numpy` available.

## 2. Procedure (The E2E Steps)

1. **Review Latest Benchmark & E2E Run Artifacts**:
   - Inspect recent run outcomes in `artifacts/e2e-report/results.json` or updated component registrations in `docs/matrix-coverage.md`.
   - Identify any score drifts, newly supported scorers, or changed tool capabilities across Test Case Gen, RCA, and Requirement Gen.

2. **Update Metrics Data**:
   - Edit `docs/eval_metrics.json` to reflect verified benchmark outcomes.
   - Ensure the JSON strictly adheres to `docs/eval_metrics_schema.json`.
   - Update `metadata.version` and `metadata.generated_date`.

3. **Validate Dataset Integrity (Check Mode)**:
   - Run dry-run validation to verify schema conformity:
     ```bash
     python scripts/generate_eval_metrics.py --check
     ```

4. **Regenerate Visual Metric Assets**:
   - Execute the generator to output both high-DPI PNG and SVG assets:
     ```bash
     python scripts/generate_eval_metrics.py --input docs/eval_metrics.json --output docs/eval_metrics_comparison.png --format both
     ```

5. **Update Narrative in Executive Report**:
   - If scores have changed significantly, review and update the summary narrative and decision tables in `docs/executive-report-eval-tools.md`.
   - Ensure all markdown links to `docs/matrix-coverage.md`, `docs/phoenix-spike.md`, and `docs/braintrust-spike.md` remain valid.

## 3. Output Contract (Definition of Done)

- `docs/eval_metrics.json` is valid JSON and conforms to `docs/eval_metrics_schema.json`.
- `docs/eval_metrics_comparison.png` exists and is non-empty (> 100KB).
- `docs/eval_metrics_comparison.svg` exists and is valid XML/SVG.
- `python scripts/generate_eval_metrics.py --check` exits with return code 0.
- `pytest tests/test_generate_eval_metrics.py` passes 100%.

## 4. Failure Handling

- If schema validation fails, inspect the missing or mismatched keys reported by `generate_eval_metrics.py`.
- Do not hardcode metrics in python scripts. All data changes must reside in `docs/eval_metrics.json`.
- If matplotlib rendering fails due to display/GUI issues, verify `matplotlib.use('Agg')` is active.

## 5. Verification Gate

Run the mechanical proof command:

```bash
python scripts/generate_eval_metrics.py --check && pytest tests/test_generate_eval_metrics.py -v
```
