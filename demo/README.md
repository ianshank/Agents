# Demo runbook — langfuse-eval-harness

A repeatable, **fully offline** demo (zero credentials, deterministic) tuned for a
mixed **engineer + leadership** audience. Runs in ~6–8 minutes.

**The one-liner:** *this is an LLM evaluation harness you can't quietly weaken* —
config-driven grading that gates CI, multi-model comparison, and **calibrated
ship / hold / escalate** decisions that fail safe to a human.

---

## Setup (once)

```bash
pip install -e . -e ./agent-core -e ./flow-protocol -e ./flow-corpus -e ./behavioral-regression
export PYTHONPATH=.        # required: lets the demo's callable target import
```

`PYTHONPATH=.` is needed because the demo's system-under-test is
`demo.support_bot_target:answer` (a deterministic offline "support bot"); the
harness imports it by dotted path.

## Fastest path — run everything

```bash
bash demo/run_demo.sh            # add --install to pip-install first
```

That runs all five beats below and writes every report to `out/demo/`. The rest
of this doc is the **spoken script**: what to type, what appears, and what to say.

---

## Beat 1 — "It's a real, pluggable harness" (~30s)

```bash
eval-harness list-plugins
```
```
scorers: contains, exact_match, json_keys, llm_judge, regex_match, weighted
datasets: csv, inline, jsonl, langfuse, parquet
targets: callable, echo, model
sinks: console, html_file, json_file, langfuse, phoenix
judges: anthropic, bedrock, mock, openai, phoenix_evals
```
- **Engineer says:** every component self-registers; third parties add their own
  via an entry-point group with **zero edits to this package**.
- **Leader hears:** it's a platform, not a script — extensible without forking.

## Beat 2 — "Config in, graded out, CI-ready" (~90s) — the core

```bash
eval-harness run --config demo/configs/eval.pass.yaml --offline
```
```
run 'support-bot-demo-…' — 10 item(s)
  mentions_settings: mean=0.900 pass_rate=0.90 n=10
  actionable_step:   mean=0.900 pass_rate=0.90 n=10
  answer_quality:    mean=0.900 pass_rate=0.90 n=10
  helpfulness:       mean=0.850 pass_rate=0.90 n=10
QUALITY GATE: PASS        (exit 0)
```
Open `out/demo/report.html` — a self-contained HTML scorecard (no server, no CDN).
- **Engineer says:** dataset, target, four scorers (incl. a `weighted` composite
  and an LLM-judge), sinks, and the gate are **all config** — no hard-coded values.
  The one out-of-scope question is the item dragging the deterministic scores to 0.9.
- **Leader hears:** every release gets the same scorecard, automatically.

## Beat 3 — "The gate has teeth" (~60s) — the CI story

```bash
eval-harness run --config demo/configs/eval.fail.yaml --offline ; echo "exit=$?"
```
```
QUALITY GATE: FAIL
  - helpfulness.mean=0.850 below min 0.95
exit=1
```
The only change from Beat 2 is **one stricter threshold**. The process **exits
non-zero**, so it drops straight into a CI step and stops the build.
- **Engineer says:** `run` is a CI gate — non-zero exit fails the pipeline.
- **Leader hears:** a quality drop can't silently ship; the build goes red.

## Beat 4 — "Multi-model comparison" (~45s)

```bash
eval-harness compare --config demo/configs/compare.yaml --offline --html out/demo/compare.html
```
```
ranked by answer_quality (mean): support_bot > echo_baseline
```
Same dataset, scorers, and judge for both models — an apples-to-apples ranking.
- **Engineer says:** point two (or ten) targets at one config; get a ranked board.
- **Leader hears:** "which model is better for us?" becomes a repeatable measurement.

## Beat 5 — "Calibrated ship / hold / escalate" (~2min) — the payoff

```bash
bregress --seed 7 --set v2_sycophancy_mean=0.15 --html out/demo/bregress_ship.html   # decision: ship
bregress --seed 7 --set v2_sycophancy_mean=0.55 --html out/demo/bregress_hold.html   # decision: hold
bregress --seed 7 --set v2_sycophancy_mean=0.30 --html out/demo/bregress_escalate.html # decision: escalate
```
The question: *did v2 get more sycophantic than v1?* The tool validates its **own
judge** (κ + statistical power), puts a **calibrated confidence interval** on the
change, runs a **canary** to prove it can separate a known regression, and only
then decides. Open any `out/demo/bregress_*.html` for the reliability diagram.

| `v2_sycophancy_mean` | What it models | Decision |
|---|---|---|
| `0.15` (below v1's 0.30) | v2 measurably **improved** | **SHIP** ✅ |
| `0.55` (above v1's 0.30) | v2 has a **real regression** | **HOLD** ⛔ |
| `0.30` (equal to v1) | **no clear change** — can't confirm it's safe | **ESCALATE** 🔎 |

- **Engineer says:** the stats are **reused** from proven monorepo primitives
  (Wilson/bootstrap CIs, κ-gate); a run is byte-reproducible from `(config, seed)`.
- **Leader hears:** it **never rubber-stamps** — when the measurement can't tell,
  it **fails safe to a human** instead of guessing. That's the trust story.

## Close — "Why you can't game it" (~30s)

The cheapest way to pass an eval is to weaken the eval. Two gates stop that:
```bash
python scripts/check_protected_changes.py --base-ref origin/main   # eval-defining files need a reviewed label
python scripts/regression_gate.py --base-ref origin/main --mode warn # blocks NET-NEW failures vs base
```
- **Leader hears:** the harness protects its own integrity — governance, not vibes.

---

## Optional live appendix (creds required — skip if offline)

`demo/configs/live.appendix.yaml` runs the **same** dataset/scorers/gate against a
**real model** and a **real LLM judge**, and streams to Langfuse. Only the `target`
and `judge` blocks change — proof the harness is model-agnostic.

```bash
export EVAL_PROVIDER=openai EVAL_MODEL=gpt-4o-mini OPENAI_API_KEY=...   # or bedrock/anthropic
# For the real judge + Langfuse sink:
export EVAL_JUDGE=anthropic ANTHROPIC_API_KEY=...
export LANGFUSE_PUBLIC_KEY=... LANGFUSE_SECRET_KEY=... LANGFUSE_BASE_URL=<your-langfuse-endpoint>  # see .env.example
PYTHONPATH=. eval-harness run --config demo/configs/live.appendix.yaml
```
Every secret/endpoint is an env var (`${VAR:-default}`) — nothing hard-coded. You
can also run `eval-harness compare` with one offline arm and one live model arm.

---

## Notes & honest caveats

- **Deterministic:** fixed seeds; offline beats are byte-reproducible. Re-run freely.
- **Auto-fix loop (F-008) is intentionally disabled scaffolding** — do **not** demo
  it as working (see `docs/decisions/0004-auto-fix-loop.md`).
- All artifacts land in `out/demo/` (gitignored). Delete it to reset.
- `demo/run_demo.sh` is the only shell script in an otherwise-Python repo — fine for
  a live terminal; on Windows run the individual commands (or via WSL).

## What's in this folder

| Path | Purpose |
|---|---|
| `run_demo.sh` | one-shot orchestrator for all five beats |
| `support_bot_target.py` | the offline "support bot" system-under-test |
| `data/support_bot.jsonl` | 10 realistic support questions |
| `configs/eval.pass.yaml` | multi-scorer eval, gate **PASS** (exit 0) |
| `configs/eval.fail.yaml` | same eval, one stricter threshold → **FAIL** (exit 1) |
| `configs/compare.yaml` | multi-model comparison (bot vs. echo baseline) |
| `configs/live.appendix.yaml` | optional live model + judge + Langfuse (creds) |
| `deck.html` | self-contained visual walkthrough for stakeholders |
