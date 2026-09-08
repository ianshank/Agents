# Review: add-agent-in-the-loop-testgen

**Reviewed tree:** `ec1ab39874af389c42300dad2f0ce473d828524c` (F-069 landed on
`cursor/testgen-agent-hygiene-9dbd` vs `main` @ `39d0311`). Hygiene corrections
in this pass are listed under Corrections; they are not silently folded into
the Pass 1 verdicts.

Peer-review protocol: `skills/openspec-peer-review` two-pass
(`references/two-pass-protocol.md`). Findings first; no claim accepted on the
strength of the OpenSpec package alone.

## Peer Review Findings

### 1. Confirmed premises

| Claim | Verdict | Evidence |
|---|---|---|
| Registered `testgen_agent` (alias `testgen-agent`) is a `TargetRunner`, not an ADR 0039 allowlist entry | **CONFIRMED** | `TARGETS.create("testgen_agent", {})` with `EVAL_HARNESS_CALLABLE_TARGET_ALLOWLIST=something_else` still constructs; F_069 check 1 |
| Generator never sees `inputs.suite` | **CONFIRMED** | `TestHomeworkAttack` + F_069 check 2; fixture `killing_suite` raises if the key is present |
| Original item's `suite` is preserved for execution | **CONFIRMED** | homework spy leaves `original.inputs["suite"] == "SECRET_CORPUS_SUITE"` |
| Missing generator / empty suite / train split fail closed with `TESTGEN_EVIDENCE_KEY` empty evidence (ADR 0038) | **CONFIRMED** | `TestFailClosed` + F_069 checks 3–4 |
| Generated killing suite is executed in-process; F-065 scorers read it | **CONFIRMED** | killed==1; F_069 check 5 scores `testgen_mutation_score` == 1.0 |
| Deck B yaml is holdout-only + advisory; Deck A yaml is still `callable` | **CONFIRMED** | `config/testgen_agent_eval.yaml`, `config/testgen_eval.yaml`; F_069 checks 6 and 8 |
| Thorough holdout is n=11 unique | **CONFIRMED** | `TestHoldoutQuoting` against `corpora/testgen/v1/eval/thorough.jsonl` |
| `is_deterministic()` is True for injected fakes and None for `generator_path` | **CONFIRMED** | `TestExecution` / `TestGeneratorPath`; do not quote `pass^k` from the fake |
| `targets/testgen.py` was not extended (size-budget) | **CONFIRMED** | pipeline lives in `targets/testgen_agent.py`; no new `architecture.yaml` edge |
| `SCHEMA_VERSION` untouched; config is additive | **CONFIRMED** | no migration; `from_dict` unused here |
| F-069 `implemented_in` is the feature commit, not HEAD | **CONFIRMED** | `6c985d2346bd885d29895eb86eadd21ccb050cb0` is an ancestor of HEAD |
| E2E pipeline journey excludes both Deck B yamls | **CONFIRMED** | `tests/integration/test_pipeline_e2e.py` `_NOT_OFFLINE_JOURNEYS` names them with a sandbox-cost reason; F_069 / M8 is the execution proof |
| Matrix M1/M2/M3/M6 + M8; alias freeze `testgen-agent` | **CONFIRMED** | `tests/test_matrix_testgen_agent.py`, `FROZEN_ALIAS_MAP`, `docs/matrix-coverage.md` freshness |
| Hooks already cover the new file; no new corpus | **CONFIRMED** | PostToolUse size-budget scans any edited `.py`; `stop-generated-artifacts.py` is corpus/matrix only — F-069 adds neither |

### 2. Defects found in the tree during review

Pinned at `ec1ab39`. These were real pre-hygiene defects, not style nits.

| # | Defect | Why it mattered |
|---|---|---|
| D1 | `_generator_view` was a **shallow** copy of `inputs` | A generator that did `view.inputs["obligations"].append(...)` mutated the original item and the `run_generated_suite` payload. The homework test only asserted the `suite` *key* was absent. |
| D2 | Digest bounds `8` and `64` were literals in `__post_init__` | AGENTS.md: numeric defaults belong on named config/module constants, not call-site magic numbers. |
| D3 | `allowed_splits=()` / `("",)` after cleaning silently rejected every item | Fail-closed at *run* time with a split error, instead of a config-time `ValueError`. An operator who cleared the list would see every item fail rather than a construction error. |
| D4 | Success path had no debug log | `design.md` required attempt / prompt / suite hashes (not the suite body). `_fail` logged; execute did not. `_execute` existed in the hygiene WIP but `run()` still duplicated the execute block and never called it. |
| D5 | `AGENTS.md` had no F-069 entry point or seam | Agents following the map would not find the pipeline or the "never allowlist `eval_harness`" rule. |
| D6 | C4 L2 named the target; no L3 runtime subsection | Import edges correctly unchanged; runtime generate → strip → execute was undocumented. |
| D7 | F_069 did not lock Deck A yaml, the empty baseline, or nested-mutation isolation | A later edit could retarget Deck A at `testgen_agent` or add `generator_path` to the empty baseline without the feature validator noticing. |
| D8 | Empty baseline yaml was never `load_config`'d in unit tests | `yaml.safe_load` of the agent yaml does not prove `EvalConfig` accepts the empty profile. |

### 3. Corrections that reshaped the design

| Before (at `ec1ab39`) | After (this pass) | Forced by |
|---|---|---|
| Shallow `dict` copy of inputs | `copy.deepcopy` of filtered inputs, `expected`, and metadata | D1; mutating-spy unit test + F_069 check 10 |
| Magic `8` / `64` | `_MIN_DIGEST_CHARS` / `_MAX_DIGEST_CHARS` | D2 / AGENTS.md call-site rule |
| Empty allowlist silently fail-closes every item | `ValueError("allowed_splits must contain at least one non-empty split name")` | D3 |
| Execute duplicated in `run()` | `run()` returns `_execute(...)`, which debug-logs hashes only | D4 |
| No AGENTS / C4 L3 / F_069 checks 8–10 | Entry point + seam; L3 flowchart; validator checks 8–10; `load_config` of empty yaml | D5–D8 |

No `SCHEMA_VERSION` bump. No new import edge. `config/testgen_eval.yaml` left byte-stable.

### 4. Attacks that died under verification

Recorded so the next reviewer does not re-raise them.

| Attack | Result | Evidence |
|---|---|---|
| Split `testgen.py` (459/500) to "make room" for the pipeline | **REFUTED** | Plan and ADR 0048: pipeline **must** live in a new file. God-file split of a file under 500 is theater. |
| Add a Makefile `testgen-agent` run target against the committed yaml | **REFUTED** | Committed `testgen_agent_eval.yaml` has **no** generator; a `make` target would fail-close every item and look like a broken recipe. |
| Edit `.gitignore` / `.dockerignore` / `.gitleaks.toml` | **REFUTED** | No new on-disk artifacts, secrets, or image layers. Theater-edits would only create drift. |
| Dependabot / ruff / mypy / numpy bumps | **REFUTED** | No new runtime deps. Ruff/mypy stay lockstep (`F_055`). Numpy is unused on this path. |
| New marketplace skill or LoopController (option b) | **REFUTED for v1** | Owner default is sequential pipeline; live generator is credential-gated; engine multi-target graphs deferred until a second scenario needs them. |
| Broaden `EVAL_HARNESS_CALLABLE_TARGET_ALLOWLIST` to `eval_harness` so YAML can name a generator in-tree | **REFUTED** | ADR 0039 + F_069: never allowlist `eval_harness`. Tests inject `generate=`; optional `generator_path` stays `tests.`-allowlisted. |
| Add a full thorough.jsonl E2E row in `test_pipeline_e2e.py` | **REFUTED** | Same sandbox cost that excludes `testgen_eval.yaml`; F_069 check 5 + matrix M8 already execute a killing suite. |
| Restate `architecture.yaml` edges in C4 L3 | **REFUTED** | C4 header forbids restating import edges; L3 documents call semantics only. |
| Human `--apply` of ADR 0037 or writing `HUMAN_AUDIT` for #200–#215 | **REFUTED** | 403 for unprivileged apply; agents must not write audit verdicts. Documented in `DECISIONS.md` §6, not executed. |
| Implement Phase 9 XOR WS-1 in this PR | **REFUTED** | Independent of Deck B; WS-1 CHARTER status is a house-doc disagreement (`DECISIONS.md` §5). |

## Skills / hooks / loops (wiring, not theater)

**Already wired (no new hook files):**

- SessionStart (`.claude/hooks/session-start.sh`) — extras install; F-069 needs no new extra.
- PostToolUse size-budget — covers `targets/testgen_agent.py` the moment it is edited.
- Stop generated-artifacts — corpus/matrix only; F-069 adds no corpus. Matrix freshness remains `python tests/test_matrix_coverage.py --check`.
- `skills/pre-pr-gate` / `make pre-pr` — the operator checklist this pass runs through.
- `skills/openspec-peer-review` — this file.
- `scripts/validations/F_069.py` is on `quality-gates.yml --cov=F_069` and `validate.py --tier fast`.

**Deferred (named, not stubbed):**

- A live-model generator skill / LoopController would be option (b) or a credential-gated workflow. Owner defaults keep CI offline. Do not add a marketplace skill that cannot run without a provider key.
- `fix_loop.py` stays DESIGN-ONLY / DISABLED (C4 data-flow). Do not enable it to "close" Deck B.

## Spec-guardian

`openspec/changes/add-agent-in-the-loop-testgen/specs/agent-in-the-loop-testgen/spec.md`
Generator Isolation SHALL still holds; this pass tightens the *copy* from shallow to
deep without changing the requirement. In-process `run_generated_suite` unchanged.
Holdout allowlist unchanged. Advisory gates unchanged.
