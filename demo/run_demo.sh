#!/usr/bin/env bash
# One-shot, fully offline demo of the langfuse-eval-harness monorepo.
#
# Runs every beat of the demo in order and writes all reports under out/demo/.
# Zero credentials, deterministic (fixed seeds) — safe to run live on stage.
#
#   bash demo/run_demo.sh            # run everything
#   bash demo/run_demo.sh --install  # also pip-install the packages first
#
# NOTE: this is the only shell script in an otherwise Python(+one .ps1) repo; it
# exists because a copy-paste-able terminal script is the point of a live demo.
set -euo pipefail               # fail fast; Beat 3 (the intentional gate failure) is quarantined below
cd "$(dirname "$0")/.."          # repo root
export PYTHONPATH=.              # so `demo.support_bot_target:answer` imports

OUT=out/demo
mkdir -p "$OUT"

banner() { printf '\n\033[1;36m========== %s ==========\033[0m\n' "$*"; }
note()   { printf '\033[2m%s\033[0m\n' "$*"; }

if [[ "${1:-}" == "--install" ]]; then
  banner "Install (editable)"
  pip install -e . -e ./agent-core -e ./flow-protocol -e ./flow-corpus -e ./behavioral-regression
fi

banner "1. It's a real, pluggable harness"
note "Every scorer/dataset/target/sink/judge self-registers — third parties add more with zero core edits."
eval-harness list-plugins

banner "2. Config in, graded out, CI-ready (PASS)"
note "A realistic offline support bot, four scorers, then a quality gate. Exits 0."
eval-harness run --config demo/configs/eval.pass.yaml --offline
note "PASS -> exit $?"

banner "3. The gate has teeth (FAIL -> non-zero exit)"
note "Same eval, one stricter threshold (helpfulness mean >= 0.95). This is what breaks CI."
set +e                          # this run is MEANT to exit non-zero; don't let -e abort the demo
eval-harness run --config demo/configs/eval.fail.yaml --offline
fail_rc=$?
set -e
note "FAIL -> exit $fail_rc (a real CI step would stop the build here)"

banner "4. Multi-model comparison"
note "The real bot vs. a naive echo baseline, same dataset/scorers/judge."
eval-harness compare --config demo/configs/compare.yaml --offline \
  --html "$OUT/compare.html" --json "$OUT/compare.json"

banner "5. Calibrated ship / hold / escalate (the payoff)"
note "behavioral-regression asks: did v2 get more sycophantic? It answers with calibrated"
note "confidence and NEVER rubber-stamps — it fails safe to escalate when it can't tell."
echo
echo "  v2 improved   ->"; bregress --seed 7 --set v2_sycophancy_mean=0.15 \
  --out "$OUT/bregress_ship.json"     --html "$OUT/bregress_ship.html"
echo "  v2 regressed  ->"; bregress --seed 7 --set v2_sycophancy_mean=0.55 \
  --out "$OUT/bregress_hold.json"     --html "$OUT/bregress_hold.html"
echo "  no clear change ->"; bregress --seed 7 --set v2_sycophancy_mean=0.30 \
  --out "$OUT/bregress_escalate.json" --html "$OUT/bregress_escalate.html"

banner "Done — reports written to $OUT/"
for f in report.html report-fail.html compare.html \
         bregress_ship.html bregress_hold.html bregress_escalate.html; do
  [[ -f "$OUT/$f" ]] && echo "  $OUT/$f" || true
done
# Open the eval report if a desktop is available (best-effort, never fatal).
if command -v xdg-open >/dev/null 2>&1 && [[ -n "${DISPLAY:-}" ]]; then
  xdg-open "$OUT/report.html" >/dev/null 2>&1 || true
elif command -v open >/dev/null 2>&1; then
  open "$OUT/report.html" >/dev/null 2>&1 || true
fi
