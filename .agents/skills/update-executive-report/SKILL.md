---
name: update-executive-report
description: Update and regenerate the evaluation tools executive report, comparative metrics, and visual presentation charts. Use this whenever the user asks to update the executive report, refresh eval tool metrics, or re-run evaluation visualization after expert-judgment restamps.
---

# Update Executive Report — E2E Action Skill

Perform the update and maintenance of the LLM Evaluation Tools Executive Report ([`docs/executive-report-eval-tools.md`](../../../docs/executive-report-eval-tools.md)), its companion visual metrics chart ([`docs/eval_metrics_comparison.png`](../../../docs/eval_metrics_comparison.png) / [`.svg`](../../../docs/eval_metrics_comparison.svg)), and the speaker deck ([`docs/plans/scenario-eval-matrices/VP_DECK.md`](../../../docs/plans/scenario-eval-matrices/VP_DECK.md)).

**Category error (do not regress):** Langfuse / Phoenix / BrainTrust are **operations UIs / sinks**, not the products that compute testgen / RCA / requirements scores. Those scorers are harness-side (F-065 / F-067 / F-068 / F-069). A Phoenix 9.5 on RCA is OpenInference UX, not `rca_ac_at_k`.

**Scoring basis:** `docs/eval_metrics.json` `metadata.scoring_basis` is `expert_judgment`. The 0–10 cells are not verified bake-off outcomes. Do not present them as measured capability scores.

**Live e2e is not a restamp path:** a `--tiers all` campaign (including PR #244) is recorded in [`docs/e2e-live-journey.md`](../../../docs/e2e-live-journey.md). Never `python tests/test_e2e_matrix.py --update` from that report — SKIP is not NOT-RUN. Never retune 0–10 cells from Langfuse/Phoenix smokes or `contains` sink PASS.

## 1. Preconditions (Input Contract)

Confirm these hold before proceeding:

- The schema definition exists at [`docs/eval_metrics_schema.json`](../../../docs/eval_metrics_schema.json).
- The current metrics dataset exists at [`docs/eval_metrics.json`](../../../docs/eval_metrics.json).
- The generator script exists at [`scripts/generate_eval_metrics.py`](../../../scripts/generate_eval_metrics.py).
- The speaker deck exists at [`docs/plans/scenario-eval-matrices/VP_DECK.md`](../../../docs/plans/scenario-eval-matrices/VP_DECK.md).
- Python environment has `matplotlib` and `numpy` available.

## 2. Procedure (The E2E Steps)

1. **Review latest evidence, not bake-off numbers**:
   - Inspect spike reports (`docs/phoenix-spike.md`, `docs/braintrust-spike.md`), registry rows in `docs/matrix-coverage.md`, and corpus honesty notes in `VP_DECK.md` / `DECK_A_PLUS.md`.
   - Identify seam/UX changes that might justify an expert-judgment restamp. Do **not** treat `artifacts/e2e-report/results.json` as a three-vendor bake-off.

2. **Update metrics data (never silently retune 0–10s)**:
   - Edit `docs/eval_metrics.json` only when the expert rationale actually changed. Do not nudge scores to make a chart look better.
   - Preserve `metadata.scoring_basis: expert_judgment` and the expert-judgment chart caption (`chart_subtitle`; optional `chart_tagline` falls back to the historic comparative-analysis line).
   - Ensure the JSON strictly adheres to `docs/eval_metrics_schema.json` (optional keys stay optional; fixtures omit them).
   - Update `metadata.version` and `metadata.generated_date` only when the dataset itself changed.

3. **Validate dataset integrity (Check Mode)**:
   - Run dry-run validation to verify schema conformity and SVG freshness:
     ```bash
     python scripts/generate_eval_metrics.py --check
     ```

4. **Regenerate visual metric assets**:
   - Execute the generator to output both high-DPI PNG and SVG assets:
     ```bash
     python scripts/generate_eval_metrics.py --input docs/eval_metrics.json --output docs/eval_metrics_comparison.png --format both
     ```

5. **Update narrative and deck**:
   - If scores or census/means changed, update `docs/executive-report-eval-tools.md` and refresh `VP_DECK.md` forbidden-numbers / honesty lines. Keep vendors = sinks.
   - Ensure markdown links to `docs/matrix-coverage.md`, `docs/phoenix-spike.md`, `docs/braintrust-spike.md`, and `VP_DECK.md` remain valid.

## 3. Output Contract (Definition of Done)

- `docs/eval_metrics.json` is valid JSON, conforms to `docs/eval_metrics_schema.json`, and still carries `scoring_basis: expert_judgment`.
- The expert-judgment caption is preserved on the chart (subtitle and/or tagline); 0–10 cells were not silently retuned.
- `docs/eval_metrics_comparison.png` exists and is non-empty (> 100KB).
- `docs/eval_metrics_comparison.svg` exists and is valid XML/SVG.
- `VP_DECK.md` forbidden-numbers match the current census/means if those changed.
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
