# C4 Architecture — langfuse-eval-harness

> **Provenance & edge semantics.** The diagrams in this document are
> hand-maintained and carry **runtime/call/protocol semantics**: the L1 context
> and L2 container edges describe who calls whom at run time and over which
> protocol, and the L3 sections document sub-component internals *below* the
> granularity of the architecture manifest. The **import-edge component view**
> is not maintained here — it is generated deterministically from
> [`architecture.yaml`](../architecture.yaml) into
> [`architecture.mmd`](../architecture.mmd) via
> `python skills/architecture-drift-guard/scripts/mermaid_gen.py --manifest architecture.yaml -o architecture.mmd`
> and is gated against the real import graph by
> `skills/architecture-drift-guard/scripts/drift_check.py` (plus a
> `mermaid_gen.py --check` freshness gate) in CI. **This document never
> restates package-level import edges.** Where an edge here resembles one
> there, the generated view is authoritative for imports and this document is
> authoritative for runtime behaviour.

## Level 1 — System Context

```mermaid
C4Context
    title System Context: Langfuse Eval Harness

    Person(dev, "Developer / CI Pipeline", "Runs evaluations, reviews scores, gates deployments")

    System(harness, "Langfuse Eval Harness", "Config-driven LLM evaluation engine with pluggable scorers, judges, and sinks")

    System_Ext(langfuse, "Langfuse Cloud", "Observability platform — stores traces, scores, and dataset items")
    System_Ext(llm_api, "LLM API", "OpenAI-compatible endpoint — NVIDIA Nemotron, LM Studio, GPT-4, etc.")
    System_Ext(snyk, "Snyk", "Dependency vulnerability scanning and monitoring")

    Rel(dev, harness, "Runs eval-harness CLI", "YAML config + CLI flags")
    Rel(harness, langfuse, "Logs scores, links traces", "HTTPS / Langfuse SDK")
    Rel(harness, llm_api, "Sends judge prompts", "HTTPS / OpenAI SDK")
    Rel(dev, langfuse, "Reviews scores and traces", "Browser")
    Rel(snyk, harness, "Scans dependencies", "Snyk CLI")
```

## Level 2 — Container Diagram

*Edges below are runtime/call relations, not import edges — see the
[generated import view](../architecture.mmd).*

```mermaid
C4Container
    title Container Diagram: Langfuse Eval Harness

    Person(dev, "Developer", "")

    Container_Boundary(harness, "Eval Harness Package") {
        Container(cli, "CLI", "Python / argparse", "Entry point — parses args, loads config, runs engine")
        Container(engine, "EvalEngine", "Python", "Orchestrates: load → sample → run → score → aggregate → emit")
        Container(config, "Config Loader", "Python / Pydantic", "YAML → migrate → interpolate → validate → EvalConfig")
        Container(core, "Core (core)", "Python", "Component contracts + generic Registry[T] with alias support (src/eval_harness/core/registry.py)")
        Container(plugins, "Plugin Loader (plugins)", "Python", "Central registries (SCORERS, JUDGES, ...) — built-in self-registration + entry-point discovery via the eval_harness.plugins group (src/eval_harness/plugins.py)")
    }

    Container_Boundary(components, "Pluggable Components") {
        Container(scorers, "Scorers", "Python", "exact_match, regex, contains, json_keys, weighted, llm_judge, autoevals")
        Container(judges, "Judges", "Python", "mock, bedrock, openai (Nemotron-compatible), anthropic, phoenix_evals")
        Container(datasets, "Datasets", "Python", "inline, jsonl, csv, parquet, langfuse, braintrust")
        Container(targets, "Targets", "Python", "echo, callable (dynamic import)")
        Container(sinks, "Sinks", "Python", "console, json_file, html_file, langfuse, phoenix, braintrust")
        Container(gating, "Quality Gate", "Python", "Config-driven pass/fail for CI")
    }

    Container_Boundary(integration, "Integrations") {
        Container(lf_client, "LangfuseClient", "Python", "Interface + NullClient + SDKClient adapter")
        Container(px_client, "PhoenixClient", "Python", "OTel span export (SDK-optional seam; mirrors LangfuseClient)")
        Container(bt_client, "BrainTrustClient", "Python", "Experiment export + dataset read (SDK-optional seam)")
        Container(skill_fw, "Skill Framework", "Python", "validate_skill.py validation + marketplace (eval + deterministic generator skills)")
    }

    Container_Boundary(siblings, "Sibling Packages (offline, deterministic)") {
        Container(agent_core_pkg, "agent_core", "Python", "Deterministic control & calibration core — calibration metrics, merge-gate subsystem, store sync (zero runtime deps)")
        Container(flow_corpus_pkg, "flow_corpus", "Python", "Flow-calibration corpus + oracles, airgapped from the harness behind flow-protocol")
        Container(behavioral_regression_pkg, "behavioral_regression", "Python", "Behavioural-regression detector + ship/hold/escalate gate (bregress CLI); offline + byte-reproducible from (BRConfig, seed)")
    }

    System_Ext(langfuse, "Langfuse Cloud", "")
    System_Ext(llm_api, "LLM API", "")

    Rel(dev, cli, "eval-harness run", "CLI")
    Rel(dev, behavioral_regression_pkg, "bregress run", "CLI")
    Rel(cli, config, "load_config()")
    Rel(cli, engine, "engine.run()")
    Rel(cli, plugins, "bootstrap(), list-plugins")
    Rel(engine, plugins, "bootstrap() + registry lookups at run time")
    Rel(plugins, core, "instantiates Registry[T] per component kind")
    Rel(engine, scorers, "score()")
    Rel(engine, judges, "evaluate()")
    Rel(engine, datasets, "load()")
    Rel(engine, targets, "run()")
    Rel(engine, sinks, "emit()")
    Rel(engine, gating, "evaluate_gate()")
    Rel(engine, lf_client, "log_score(), link_dataset_item()")
    Rel(lf_client, langfuse, "HTTPS")
    Rel(sinks, px_client, "log_score() as OTel spans")
    Rel(sinks, bt_client, "log_item() per item")
    Rel(datasets, bt_client, "fetch_dataset_items()")
    Rel(judges, llm_api, "chat.completions.create()")
    Rel(behavioral_regression_pkg, agent_core_pkg, "wilson_interval(), brier_decomposition(), reliability_bins(), logging (runtime calls)")
    Rel(behavioral_regression_pkg, flow_corpus_pkg, "validate_oracle() kappa-gate, power checks, bootstrap CIs (runtime calls)")
    Rel(flow_corpus_pkg, agent_core_pkg, "metric primitives — Murphy decomposition, Cohen's kappa, Wilson (runtime calls)")
```

All engine edges above (`engine → scorers/judges/datasets/targets/sinks/gating/...`)
are **runtime-call semantics** — the engine resolves those components by name
through the plugin registries and invokes them; the package-level import edges
behind this wiring live only in the generated
[import view](../architecture.mmd).

## Level 3 — Component: EvalEngine

*Edges below are runtime/call relations, not import edges — see the
[generated import view](../architecture.mmd). This diagram is sub-manifest
granularity: it documents internals of the single `engine` component.*

```mermaid
C4Component
    title Component Diagram: EvalEngine

    Container_Boundary(engine_boundary, "EvalEngine") {
        Component(from_config, "from_config()", "classmethod", "Bootstrap registries, resolve components, inject client")
        Component(run_method, "run()", "method", "Orchestrate full evaluation: load → sample → score → aggregate → emit")
        Component(run_one, "_run_one()", "method", "Execute single item: target.run() → scorer.score() → link trace")
        Component(sample, "_sample()", "method", "Deterministic sampling via seeded RNG")
        Component(aggregate, "_aggregate()", "staticmethod", "Compute mean, pass_rate per scorer across all items")
    }

    Container_Boundary(deps, "Dependencies") {
        Component(config_model, "EvalConfig", "Pydantic", "Validated configuration with schema versioning")
        Component(run_context, "RunContext", "dataclass", "Per-run context — config, judge, RNG, clock")
        Component(run_result, "RunResult", "dataclass", "Aggregated scores, item results, timing")
    }

    Rel(from_config, run_method, "creates engine, then caller invokes run()")
    Rel(run_method, sample, "filter items by sample_rate")
    Rel(run_method, run_one, "for each sampled item")
    Rel(run_method, aggregate, "after all items scored")
    Rel(run_one, run_context, "threaded through scorers")
    Rel(run_method, run_result, "produces")
    Rel(from_config, config_model, "validated input")
```

## Level 3 — Component: Calibrated Merge Gate (F-010 + F-032…F-035, agent_core, default-off)

A pure, deterministic merge-decision subsystem under `agent_core` (ADR 0005), wired by
`.github/workflows/calibrated-merge-gate.yml`. It **auto-merges nothing** unless
`ENABLE_CALIBRATED_AUTOMERGE` is set and a populated, human-audited outcome store has earned it.
Outcomes are labelled by **real** detectors (git history + GitHub Actions check-runs), all
timeout-bounded and failing safe.

Real data flows through the subsystem via the F-032…F-035 activation (ADR 0018): the store
persists on the dedicated `merge-gate-data` branch (`store_sync` — canonical deterministic
merge because `resolved()` is file-order dependent; plumbing commits; retry-with-backoff for
concurrent writers; unparseable lines preserved verbatim), seeded on every push to `main`,
passively labelled daily, audited weekly through GitHub issues, and observed by an always-on
**shadow** job that logs a decision on every PR without ever blocking one.

Seed routing (F-042, ADR 0023) decides each record's lane by the merged change's **PR
head-ref prefix** (`config/agent-authors.yaml`, e.g. `claude/*`): an agent change is seeded in
the un-prefixed **agent domain** with the real `agent_version` and a deterministic proxy
confidence (`scripts/agent_confidence.py`), while every human, PR-less, or unclassifiable
change — and any classifier failure, fail-safe — keeps the reserved `human/<domain>` namespace
at confidence 0.0 (human outcomes never enter agent-domain calibration). This is what makes the
agent-domain corpus non-degenerate; `agent_core.calibration_report` (F-043) reports its
calibration (ECE/Brier/AUROC/abstention, Wilson CIs, honest `DEGENERATE` guard) to the daily
labeller summary, and a one-off reversible backfill
(`scripts/migrations/agent_domain_backfill.py`, F-044) re-attributed the historical agent SHAs.

```mermaid
C4Component
    title Component Diagram: Calibrated Merge Gate (agent_core)

    Container_Boundary(gate, "agent_core merge-gate subsystem") {
        Component(ci, "merge_gate_ci", "CLI entrypoint", "exit 0/10/20 (+1 internal, +2 usage); --audit-log JSONL")
        Component(decide, "merge_gate.decide()", "pure function", "REJECT mech-fail -> ESCALATE protected -> calibrated trust + Wilson bin floor -> AUTO_MERGE")
        Component(store, "outcome_store", "append-only JSONL", "OutcomeStore, BinningCalibrator, build_domain_models (held-out fold)")
        Component(sync, "store_sync", "package + CLI (F-032)", "models/serialization/store/git_sync submodules; pull/push/stats vs merge-gate-data branch; canonical merge, opaque-line preservation, retry-backoff; byte-oriented git-plumbing runner (shared subprocess_util); exit 0/4/5")
        Component(labeller, "outcome_labeller", "module", "passive revert / CI-failure / timeout-clean labels (alerting only)")
        Component(sampler, "audit_sampler", "module", "unbiased stratified sampling + HUMAN_AUDIT verdicts")
        Component(detectors, "detectors", "module", "GitRevertDetector, GitHubChecksFailureAttributor, resolve_repo; DetectorConfig timeouts, fail-safe")
        Component(calib, "calibration", "module", "Wilson interval, AUROC, ECE (reused, not re-implemented)")
        Component(report, "calibration_report", "read-only CLI (F-043)", "agent-domain ECE/Brier/AUROC/abstention (Wilson CIs); HUMAN_AUDIT vs passive views tagged; honest DEGENERATE guard; ReportConfig knobs; reuses calibration")
        Component(domains, "domains", "module", "single-source HUMAN_NAMESPACE / is_agent_domain / strip_human_namespace (agent vs reserved-human lane; yaml/config-free)")
    }

    System_Ext(git, "git", "Local history — revert footer detection")
    System_Ext(gha, "GitHub Actions", "Commit check-runs via gh api")
    System_Ext(branch, "merge-gate-data branch", "Persistent outcome store (ADR 0018); orphan-bootstrapped, [skip ci] commits, actor trailers")

    Rel(ci, decide, "decide(ctx, calibrator, health, tau, bin)")
    Rel(ci, store, "build_domain_models()")
    Rel(decide, calib, "wilson_interval()")
    Rel(store, calib, "auroc / ECE / wilson")
    Rel(sync, branch, "fetch-gated pull / plumbing-commit push")
    Rel(sync, store, "canonical merged JSONL")
    Rel(labeller, detectors, "was_reverted() / caused_failure()")
    Rel(labeller, store, "append passive labels")
    Rel(sampler, store, "select + record HUMAN_AUDIT")
    Rel(detectors, git, "git log (-z, revert footer)")
    Rel(detectors, gha, "gh api check-runs")
    Rel(report, store, "read agent-domain slice")
    Rel(report, calib, "auroc / brier / wilson / selective-risk")
    Rel(report, domains, "is_agent_domain() lane filter")
```

The CI surfaces around the subsystem (scripts layer + workflows): `merge_gate_context.py`
composes the ChangeContext (path→domain from `config/merge-gate-domains.yaml`,
`touches_protected` from `eval_protected_paths`, mech_pass from the regression gate) and
carries the F-042 `--confidence` seam that stamps the seed's `raw_confidence`;
`agent_confidence.py` (F-042) is the deterministic proxy scorer — a pure function of diff
size / file count / test-ratio / protected-path touches through a clamped sigmoid (no network,
no model) that classifies the agent lane and emits its `agent_version` + confidence;
`scripts/_config.py` is the shared changed-file / strict-YAML-loader helper both reuse;
`scripts/migrations/agent_domain_backfill.py` (F-044) is the one-off reversible re-attribution;
`record_audit_verdict.py` is the idempotent, SHA-validated verdict wrapper (the only
HUMAN_AUDIT writer, dispatch-triggered); `audit_issue_sync.py` plans deduped audit issues.
Workflows: `merge-gate-seed.yml` (push:main — F-042 head-ref routing, fail-safe to the human
lane), `outcome-labeller.yml` (daily, checks:read precondition guard, F-043 calibration-report
summary), `merge-gate-audit.yml` (weekly reader), `merge-gate-verdict.yml` (workflow_dispatch
only, environment-gated), and the always-on `shadow` job in `calibrated-merge-gate.yml`.

## Level 3 — Component: Flow Calibration Corpus (F-011…F-015, airgap seam)

A calibration corpus of agentic flow variants (`flow-corpus`) that emits results across a
versioned contract (`flow-protocol`) for the harness to calibrate against. The corpus reuses
`agent_core`'s metric primitives (Murphy decomposition, Cohen's κ, Wilson intervals,
selective risk-coverage, `OutcomeRecord`) but **never** imports `eval_harness`. `flow-protocol`
is the *only* shared surface; the airgap is enforced deterministically by the grimp drift gate
(`architecture.yaml` declares only `flow_corpus → {flow_protocol, agent_core}` — no
corpus↔harness edge), and a two-way version pin (`verify_pins`) trips on `flow_protocol`/
`agent_core` skew.

```mermaid
C4Component
    title Component Diagram: Flow Calibration Corpus (airgap seam)

    Container_Boundary(proto, "flow-protocol (shared contract)") {
        Component(contract, "contract", "Pydantic v2 (frozen)", "FlowResult / OracleResult / ConfidenceChannel")
        Component(pver, "version", "semver", "PROTOCOL_VERSION + migrate_protocol")
    }

    Container_Boundary(corpus, "flow-corpus") {
        Component(specimens, "specimens", "Policy-injected flows", "baseline (control), MCTS, ReAct (type-holdout) + MockPolicy seam")
        Component(suites, "suites/sdlc", "task population", "declared-N deterministic suite + snapshot")
        Component(oracles, "oracles", "property + kappa_gate", "deterministic verdict; Cohen's-κ validation (co-determinate, power-aware)")
        Component(runner, "validation.runner", "orchestrator", "keyed OutcomeRecords + Brier reliability + AURC")
        Component(holdout, "holdout", "manager + rotation", "instance- vs type-holdout (single split authority); rotation stability")
        Component(crosscheck, "crosscheck", "ablation", "confidence vs flow-type indicator + bootstrap-CI significance")
        Component(keying, "keying + partition", "deterministic hashing", "version_key (impl+config; task excluded); bucket()")
        Component(pinning, "pinning", "tripwire", "verify_pins(): protocol + harness version pins")
        Component(ccfg, "config", "CorpusConfig", "all thresholds; derived max_indeterminate_rate")
    }

    System_Ext(ac, "agent_core (public API)", "calibration, golden.cohen_kappa, OutcomeRecord, logging_util")

    Rel(specimens, contract, "emit FlowResult")
    Rel(oracles, contract, "emit OracleResult")
    Rel(runner, specimens, "run over suite")
    Rel(runner, oracles, "judge")
    Rel(runner, ac, "brier_decomposition / selective_risk_coverage / OutcomeRecord")
    Rel(oracles, ac, "cohen_kappa")
    Rel(holdout, keying, "bucket() partitions")
    Rel(pinning, pver, "PROTOCOL_VERSION pin")
    Rel(pinning, ac, "agent_core __version__ pin")
```

Reliability (the Brier/Murphy *reliability* term) is the primary, gating calibration metric;
ECE is diagnostic only. Any metric below a power-derived minimum sample is *directional only* and
cannot gate. Corpus `OutcomeRecord`s use a `"corpus_oracle"` label source (never `HUMAN_AUDIT`) so
they can never be mistaken for the harness's unbiased human-audit sample.

## Quality & Eval-Integrity Gates

These gates run in CI (`.github/workflows/quality-gates.yml`; the operational-scripts
lint/type/coverage gate, F-031, runs in `eval-harness-ci.yml`) and guard the harness
against the Goodhart failure mode where the cheapest path to "green" is weakening the
evaluation itself rather than fixing the code.

```mermaid
flowchart TB
    PR[Pull Request] --> VAL[validate.py<br/>features.yaml schema + DAG + provenance]
    PR --> COV[Tooling coverage gate<br/>>=85% on gate modules]
    PR --> SCOV[Operational-scripts gate F-031<br/>ruff + mypy + >=85% coverage on scripts/]
    PR --> REG[regression_gate.py]
    PR --> GUARD[check_protected_changes.py]
    PR --> DRIFT[check_skill_script_drift.py<br/>vendored skill copies == canonical]
    PR --> CHARTER[check_charter_drift.py<br/>docs/CHARTER.md references resolve — via test suite]
    PR --> MG[calibrated-merge-gate.yml<br/>F-010 acting job — default-off]
    PR --> SHADOW[shadow job F-035<br/>log-only, never blocks]

    subgraph Regression Gate F-006
        REG --> WT[git worktree<br/>isolated HEAD baseline]
        WT --> DIFF[ruff + offline pytest<br/>in both trees]
        DIFF --> NET{net-new findings?}
        NET -->|yes & block| FAIL1[exit 1]
        NET -->|no| PASS1[exit 0]
    end

    subgraph Eval-Integrity Guard F-007
        GUARD --> MATCH[eval_protected_paths.py<br/>single source of truth]
        MATCH --> PROT{protected path changed?}
        PROT -->|yes, unapproved| FAIL2[exit 1 — needs label/CODEOWNERS]
        PROT -->|no, or approved| PASS2[exit 0]
    end

    subgraph Calibrated Merge Gate F-010
        MG --> ENABLED{ENABLE_CALIBRATED_AUTOMERGE?}
        ENABLED -->|no| SKIP[skipped — neutral, never fails PRs]
        ENABLED -->|yes| DECIDE[merge_gate_ci.decide]
        DECIDE --> RC{exit code}
        RC -->|0 AUTO_MERGE| MERGE[enable auto-merge]
        RC -->|10 ESCALATE| HUMAN[needs-human-review]
        RC -->|20 REJECT / 1,2 error| FAIL3[exit 1]
    end

    subgraph Real-Data Activation F-032…F-035 — ADR 0018
        SHADOW -->|store_sync pull, read-only| DATA[(merge-gate-data branch<br/>merge_outcomes.jsonl)]
        SHADOW --> SUMMARY[step summary:<br/>agent + human/ decisions, store stats]
        MAIN[push: main] --> SEED[merge-gate-seed.yml<br/>F-042 head-ref routing:<br/>agent domain @ proxy conf / human/ @ 0.0]
        SEED -->|store_sync push| DATA
        CRON1[daily cron] --> LAB[outcome-labeller.yml<br/>checks:read guard<br/>+ F-043 calibration report]
        LAB -->|passive labels, push| DATA
        CRON2[weekly cron] --> AUD[merge-gate-audit.yml<br/>reader: deduped issues]
        AUD -->|store_sync pull| DATA
        AUD --> ISSUES[merge-gate-audit issues]
        ISSUES --> DISPATCH[merge-gate-verdict.yml<br/>workflow_dispatch, env-gated]
        DISPATCH -->|HUMAN_AUDIT verdict, push| DATA
    end

    FIX[fix_loop.py<br/>DESIGN-ONLY / DISABLED] -.->|ScopeGuard blocks protected writes| MATCH
```

These CI gates run per-file/per-package. For a local, whole-repo pass, `scripts/run_all_e2e.ps1`
is a **test orchestrator** (not a runtime component — it adds no edges to the import graph above):
it runs every package suite, every `features.yaml` functionality gate (Tier B calls `validate.py`),
a curated set of package CLI journeys (`eval-harness`, `bregress`, `merge_gate_ci`,
`skill_marketplace`), the skill/hook e2e tests, and credential-gated live integrations, and
aggregates one report under `artifacts/e2e-report/`. See [e2e-runbook.md](e2e-runbook.md).

## Data Flow

*Edges below are runtime/call relations, not import edges — see the
[generated import view](../architecture.mmd).*

```mermaid
flowchart LR
    A[YAML Config] -->|load_config| B[EvalConfig]
    B --> C[EvalEngine.from_config]
    C --> D[Dataset.load]
    D --> E[Sample Items]
    E --> F[Target.run]
    F --> G[Scorer.score]
    G --> H{Judge needed?}
    H -->|Yes| I[Judge.evaluate]
    I --> J[Aggregate]
    H -->|No| J
    J --> K[Quality Gate]
    K -->|Pass| L[Sink.emit]
    K -->|Fail| M[Exit code 1]
    L --> N[Langfuse / Phoenix / BrainTrust / JSON / Console]
```
