# Live e2e capture (Windows, 2026-09-15)

STYLE: runbook. This is the committed evidence for a **real** generate →
score → judge round-trip. It is **not** the eval-UI decision package
([`plans/scenario-eval-matrices/`](plans/scenario-eval-matrices/VP_DECK.md))
and it is **not** a restamp of [`e2e-matrix/`](e2e-matrix/README.md).

This capture continued [PR #244](https://github.com/ianshank/Agents/pull/244)
(`cursor/e2e-vp-capture-eefa`) rather than opening a sibling branch.

## Invocation

| Field | Value |
|---|---|
| Date | 2026-09-15 |
| Host | Windows 10, PowerShell 5.1 (`powershell.exe`, not Git Bash) |
| Worktree | `.claude/worktrees/e2e-vp-capture` on `cursor/e2e-vp-capture-eefa` |
| SHA at run | `d5b01b22c0a9558918d0cd36c4d893fa388f39bd` |
| Command | `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run_all_e2e.ps1 -Tiers all -HypothesisProfile ci` |
| Model id | `nvidia/nemotron-3-nano-omni:2` (LM Studio; OpenAI-compatible `/v1`) |
| Phoenix | `arizephoenix/phoenix:17.18.0` on `http://127.0.0.1:6006` |
| Report | gitignored `artifacts/e2e-report/summary.json` (redacted here) |

The runner injects `.env` **only at Tier D**. Tiers A–C stay credential-free
on purpose.

## Honesty gates

Treat the campaign as a live miss if any of these fail, even when the script
exits 0.

| Gate | Result |
|---|---|
| Host log is `live target/judge: model/<id>` not `echo+mock` | **PASS** — `model/nvidia/nemotron-3-nano-omni:2 (real round-trip)` |
| Fixture YAML `type: model` **and** `prompt_template: "{question}"` | **PASS** — `artifacts/e2e-report/fixtures/live_openai.yaml` (and both sink YAMLs) |
| `live:judge-openai` is a non-empty completion, not `KeyError: 'prompt'` | **PASS** — follow-up JSON sink: `error=None`, `output_len=2`, `keyerror_prompt=False`, `helpfulness=1.0` (`llm_judge`) |
| `live:langfuse-smoke` PASS (FAIL ≠ SKIP) | **PASS** (3.3s) — smoke wrote `e2e_smoke=1.0` via OS trust |
| `live:phoenix-smoke` PASS (TCP probe) | **PASS** (0.9s) — collector reachable; OTLP export also logged HTTP 405 (fire-and-forget) |
| `live:langfuse-sink` / `live:phoenix-sink` | **PASS** on **`contains`** (`mentions_reset` / `"reset"`), **not** LLM scoring |

`prompt_template: "{question}"` is the D-3 close: `ModelTarget` defaults to
`"{prompt}"` while live items only set `inputs.question`. Missing that key
is a `KeyError`, an empty gate still exits 0, and the host log still claims
a real round-trip. Both `scripts/run_all_e2e.ps1` and `scripts/run_all_e2e.sh`
now emit the template. Re-run `python -m pytest tests/test_e2e_driver_parity.py` after
editing either driver.

## Campaign table (`summary.json`)

Tiers: `all` · HypothesisProfile: `ci` · **PASS 32 / FAIL 4 / SKIP 2** ·
~11 minutes.

The four FAILs are **missing extras on this venv**, not live SKIP-and-present.
They were confirmed PASS after `pip install -e ".[autoevals,archguard]"`
(see [Provisioning FAILs](#provisioning-fails-not-live-skips)). Live steps
were already green before that install.

| Tier | Step | Status | Detail | ms |
|------|------|--------|--------|----|
| PRE | preflight-imports | PASS | sibling imports | 0 |
| A | suite:root | FAIL | `autoevals` extra absent (`test_m8_text_scorers_pipeline`) | 143438 |
| A | suite:agent-core | PASS | 921 tests | 78927 |
| A | suite:behavioral-regression | PASS | 161 tests | 28776 |
| A | suite:flow-corpus | PASS | 163 tests | 11381 |
| A | suite:flow-protocol | PASS | 21 tests | 2054 |
| A | suite:claude-foundation | PASS | 140 tests | 6951 |
| A | suite:scripts-gate | FAIL | same `autoevals` miss | 124495 |
| B | features:validate.py | FAIL | F-009 / F-011 need `grimp` (`archguard` extra) | 46874 |
| B | matrix:coverage-check | PASS | | 1739 |
| C | e2e:skills+hooks | FAIL | drift-guard e2e needs `grimp` | 7570 |
| C | e2e:backend-validation | PASS | 357 tests | 26474 |
| C | cli:eval-harness list-plugins | PASS | | 992 |
| C | cli:eval-harness run | PASS | | 1028 |
| C | cli:eval-harness run --set | PASS | | 986 |
| C | cli:eval-harness compare | PASS | | 1026 |
| C | cli:eval-harness campaign record | PASS | | 963 |
| C | cli:eval-harness campaign analyze | PASS | | 1012 |
| C | cli:bregress | PASS | | 1148 |
| C | cli:merge_gate_ci | PASS | decision exit 10 | 510 |
| C | cli:agent_confidence (agent lane) | PASS | | 459 |
| C | cli:merge_gate_context (--confidence) | PASS | | 522 |
| C | cli:merge_seed (report store) | PASS | | 560 |
| C | cli:audit_sampler select --with-propensity | PASS | | 474 |
| C | cli:audit_sampler record --selection-propensity | PASS | | 509 |
| C | cli:calibration_report (wilson) | PASS | | 520 |
| C | cli:calibration_report (--estimator ppi++) | PASS | | 512 |
| C | cli:proxy_eval (json) | PASS | | 530 |
| C | cli:proxy_eval json-valid | PASS | | 0 |
| C | cli:skill_marketplace list | PASS | | 412 |
| C | cli:skill_marketplace verify | PASS | | 555 |
| D | live:langfuse-smoke | PASS | | 3346 |
| D | live:phoenix-smoke | PASS | | 911 |
| D | live:judge-openai | PASS | `llm_judge` / local model | 16425 |
| D | live:judge-anthropic | SKIP | `ANTHROPIC_API_KEY` not set | 0 |
| D | live:judge-bedrock | SKIP | AWS keys not set | 0 |
| D | live:langfuse-sink | PASS | `contains` only | 69372 |
| D | live:phoenix-sink | PASS | `contains` only | 65550 |

## What the user journey actually is

**Tier C** is the offline **user journey**: `eval-harness`
`list-plugins` / `run` / `run --set` / `compare` / `campaign`, merge-gate
reporting CLIs (`merge_gate_ci`, `merge_seed`, `audit_sampler`,
`calibration_report`, `proxy_eval`), `bregress`, and
`scripts/skill_marketplace.py`. Those steps use echo / MockJudge /
`--offline` **by design**. Do not quote them as a live model round-trip.

**Tier B** is `scripts/validate.py` over the **68 `done` F-IDs**. F-008 and
F-036 stay deferred. Never quote 68/68.

**`suite:root` is not live pytest.** `.env` is applied only at Tier D.
Root `addopts` has no `-m "not integration"`; integration tests **collect**
inside `suite:root` and **skip** without env. A green `suite:root` is not
Langfuse / Phoenix / NVIDIA / BrainTrust pytest.

## What is still mock / unused

- **All of Tier C** — echo, MockJudge, `--offline`.
- **`live:langfuse-sink` / `live:phoenix-sink`** — scorer is `contains`.
  `$LiveJudge` in those YAMLs is unused for scoring. `llm_judge` is
  `live:judge-openai`. Do not tell a VP that Langfuse or Phoenix received
  live LLM scores on the back of `contains`.
- **Anthropic / Bedrock** — SKIP (no keys). Intentional; do not fail the
  campaign for them.
- **NVIDIA cloud and BrainTrust** — **zero runner steps**. Not SKIP: not
  exercised. Optional `pytest tests/integration -m integration` /
  `tests/test_phoenix_live.py` were not required for this capture.
- **Phoenix sink spans** — `configure_tracing` is contractually forbidden
  from raising. The first campaign logged
  `phoenix.otel.register() failed; tracing disabled: No module named 'botocore'`.
  The extras-present rerun installed `botocore` and `register` ran; it still
  logged `DependencyConflict` (missing `boto3`) and smoke OTLP HTTP 405.
  Do not cite sink PASS as “spans arrived”. Smoke PASS is the TCP probe.
- **Langfuse sink OTLP** — certifi TLS failed against the cloud host
  (`CERTIFICATE_VERIFY_FAILED`). Smokes use OS trust and still PASS. That
  is infra (`truststore`), not “Langfuse broken”. Sink PASS remains
  `contains`.
- **Windows `_bash_works()` skips** — after extras, `e2e:skills+hooks` is
  77 passed / **15 skipped**. Those skips are WSL-bash / symlink probes,
  not mock. Documented in the runbook; not a live miss.

## Provisioning FAILs (not live SKIPs)

The first campaign venv followed the narrow extra list
(`dev,langfuse,openai,phoenix,phoenix-evals,parquet,e2e-matrix`) and omitted
`autoevals` (CI installs it) and `archguard` (`grimp`, required by F-009 /
F-011 and drift-guard e2e). After installing both:

| Step | Confirmation |
|---|---|
| `test_m8_text_scorers_pipeline` | PASS |
| `scripts/validate.py -v` | `OK: 68 done; ran 68 for tier(s) ['fast']` |
| drift-guard `test_end_to_end.py` | 10 passed |
| skills+hooks (runner flags) | 77 passed, 15 skipped |

A later `--tiers all` with those extras in the venv *before* Tier A would
be 36 PASS / 0 FAIL / 2 SKIP on this host. The same-day rerun below confirmed
that count and **did** overwrite gitignored `artifacts/e2e-report/`.

## Confirmed rerun (same host, extras present)

| Field | Value |
|---|---|
| Date | 2026-09-15 |
| SHA at run | `0665f4d` |
| Command | `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run_all_e2e.ps1 -Tiers all -HypothesisProfile ci` |
| Duration | ~15 min (`elapsed_ms` 883931) |
| Summary | **PASS 36 / FAIL 0 / SKIP 2** (Anthropic + Bedrock) |

Honesty on this report:

| Gate | Result |
|---|---|
| Host log `model/nvidia/nemotron-3-nano-omni:2` not echo+mock | **PASS** |
| Fixtures `type: model` and `prompt_template: "{question}"` | **PASS** |
| `live:judge-openai` `helpfulness` mean 1.0, QUALITY GATE PASS, no `KeyError: 'prompt'` | **PASS** |
| `live:langfuse-smoke` / `live:phoenix-smoke` | **PASS** (Langfuse `e2e_smoke`; Phoenix TCP + 405 on one OTLP path) |
| Sink PASS is `contains` (`mentions_reset`) | **PASS** — not LLM scores in Langfuse/Phoenix |
| Langfuse sink OTLP | still certifi `CERTIFICATE_VERIFY_FAILED` |
| Phoenix `botocore` | installed for this rerun; `phoenix.otel.register` ran. Remaining: `DependencyConflict` missing `boto3`. Do not cite sink PASS as spans arrived |

`e2e:skills+hooks` JUnit count is 92 (was 77 passed / 15 `_bash_works` skips after extras — same 92 collected).

## F-067 RCA mocked vs unmocked (not in the e2e driver)

Judge-free. Mocked target is `rca_maxz`. Unmocked is a gitignored JSON adapter
(`artifacts/rca_unmocked/`, ADR 0039 allowlist `rca_live_target` for that
process only) over LM Studio `nvidia/nemotron-3-nano-omni:2`. Same five scorers.
Gold `expected` / `inputs.onset` were not in the live prompt. Full 96-item live
pass was not run.

| Run | n | AC@1 mean | abstention mean | FAR mean | onset mean | gate |
|---|---|---|---|---|---|---|
| `config/rca_eval.yaml` (`rca_maxz`) | 96 | 0.333 (advisory min 0.30) | 0.719 (advisory min 0.80, miss) | 0.000 (advisory max 0.20) | 0.000 | PASS (advisory) |
| mocked 12-item slice | 12 | 0.333 | 0.667 | 0.000 | 0.000 | PASS (advisory) |
| live 12-item slice | 12 | 0.500 | 0.750 | 0.250 (advisory miss) | 0.750 | PASS (advisory) |

Live parse health: 12/12 items scored with no target error (JSON diagnoses).
Live FAR miss is confident rank on all three unanswerable slice items, not a
parse failure. Not a bake-off: corpus `events` often name the cause; the
baseline never claims onset. Manifest `baseline_strict_ac1` remains the
per-cell floor for `rca_maxz`, not the live slice.

## Matrix pin

**Do not** `python tests/test_e2e_matrix.py --update` from this `--tiers all`
report. Nightly freshness and PR #244 pin [`docs/e2e-matrix/`](e2e-matrix/e2e-matrix.md)
to the **offline** POSIX invocation (31 PASS, Tier D `NOT-RUN`). Mixing SKIP
vs NOT-RUN is the defect the restamp avoided.

A local `--check` while this live `artifacts/e2e-report/` is still on disk
**will** report stale (FAIL rows, SKIP vs NOT-RUN). That is expected. Do not
treat it as a reason to restamp. CI freshness regenerates from `--tiers offline`.

## Speaker pointer

Keep Phoenix as the default **operations UI** recommendation. This capture
does not reorder expert-judgment 0–10 cells in `docs/eval_metrics.json`.
See [`plans/scenario-eval-matrices/VP_DECK.md`](plans/scenario-eval-matrices/VP_DECK.md).

## Follow-up — NVIDIA / Langfuse / BrainTrust (same host, after the runner)

Not an e2e-driver restamp. Keys lived only in uncommitted `.env`. **Rotate them** — they were pasted in chat.

| Surface | Result |
|---|---|
| NVIDIA NIM `OpenAIJudge` (`tests/integration/test_nvidia_judge_live.py::TestNemotronInference::test_evaluates_simple_qa`) | **PASS** (78s). Model `nvidia/nemotron-3.5-lightning-30b-a3b` (listed `/v1/models`; default ultra-550b was listed but nano 404 / nano-omni 503). `OPENAI_BASE_URL` unset so this did not hit LM Studio. |
| `scripts/smokes/langfuse_smoke.py` | **PASS** |
| `tests/test_braintrust_live.py` | **SKIP** ×2 (`BRAINTRUST_TEST_PROJECT`/`DATASET` unset; Factuality needs `OPENAI_API_KEY` which was left unset to avoid LM Studio) |
| BrainTrust `build_client(enabled=True)` + `log_item` | SDK client constructed (not `NullBrainTrustClient`); **flush 401** — key rejected as not a Cognito JWT. Batch dropped. Not a live BrainTrust write. |

This NVIDIA judge call is `llm_judge`-class scoring. It is **not** a BrainTrust or Langfuse LLM-score bake-off.
