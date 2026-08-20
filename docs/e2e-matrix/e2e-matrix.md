<!-- GENERATED FILE - do not edit by hand.
     Regenerate: python tests/test_e2e_matrix.py --update
     Freshness-gated by tests/test_e2e_matrix.py::test_matrix_artifact_is_fresh. -->

# End-to-end test matrix

## Test Matrix

| Tier | Area | Step | Command | Workdir | Required Credentials | Status | Detail | Duration (ms) | Tests | Failures | Errors | Skipped | Evidence |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | suite | suite:agent-core | python -m pytest --cov --cov-report=term-missing --junitxml=$junit -p no:cacheprovider | agent-core |  | PASS | 714 tests | 47591 | 714 | 0 | 0 | 2 | artifacts/e2e-report/suite_agent-core.log |
| A | suite | suite:behavioral-regression | python -m pytest --cov --cov-report=term-missing --junitxml=$junit -p no:cacheprovider | behavioral-regression |  | PASS | 89 tests | 20250 | 89 | 0 | 0 | 0 | artifacts/e2e-report/suite_behavioral-regression.log |
| A | suite | suite:claude-foundation | python -m pytest --cov --cov-report=term-missing --junitxml=$junit -p no:cacheprovider | claude-foundation |  | PASS | 136 tests | 6791 | 136 | 0 | 0 | 1 | artifacts/e2e-report/suite_claude-foundation.log |
| A | suite | suite:flow-corpus | python -m pytest --cov --cov-report=term-missing --junitxml=$junit -p no:cacheprovider | flow-corpus |  | PASS | 119 tests | 4876 | 119 | 0 | 0 | 0 | artifacts/e2e-report/suite_flow-corpus.log |
| A | suite | suite:flow-protocol | python -m pytest --cov --cov-report=term-missing --junitxml=$junit -p no:cacheprovider | flow-protocol |  | PASS | 21 tests | 2389 | 21 | 0 | 0 | 0 | artifacts/e2e-report/suite_flow-protocol.log |
| A | suite | suite:root | python -m pytest --cov --cov-report=term-missing --junitxml=$junit -p no:cacheprovider | . |  | PASS | 995 tests | 40601 | 995 | 0 | 0 | 11 | artifacts/e2e-report/suite_root.log |
| A | suite | suite:scripts-gate | python -m pytest tests --cov=scripts --cov-config=scripts/.coveragerc --cov-report=term-missing --junitxml=$scriptsXml -p no:cacheprovider | . |  | PASS | 995 tests | 39940 | 995 | 0 | 0 | 11 | artifacts/e2e-report/suite_scripts-gate.log |
| B | features | features:validate.py | python scripts/validate.py -v | . |  | PASS |  | 33088 |  |  |  |  | artifacts/e2e-report/features_validate.py.log |
| B | matrix | matrix:coverage-check | python tests/test_matrix_coverage.py --check | . |  | NOT-RUN | not reached in this run |  |  |  |  |  |  |
| C | cli | cli:agent_confidence (agent lane) | python scripts/agent_confidence.py --files src/eval_harness/x.py tests/test_x.py --lines-changed 40 --head-ref claude/e2e-journey --output $acJson | . |  | PASS |  | 516 |  |  |  |  | artifacts/e2e-report/cli_agent_confidence__agent_lane_.log |
| C | cli | cli:audit_sampler record --selection-propensity | python -m agent_core.audit_sampler --store $reportStore record --change-id e2e0001 --correct --selection-propensity 1.0 | . |  | PASS |  | 506 |  |  |  |  | artifacts/e2e-report/cli_audit_sampler_record_--selection-propensity.log |
| C | cli | cli:audit_sampler select --with-propensity | python -m agent_core.audit_sampler --store $reportStore select --base-rate 1.0 --per-domain-floor 0 --with-propensity | . |  | PASS |  | 531 |  |  |  |  | artifacts/e2e-report/cli_audit_sampler_select_--with-propensity.log |
| C | cli | cli:bregress | python -m behavioral_regression --seed 7 --out $brJson --html $Report br.html | . |  | PASS |  | 1166 |  |  |  |  | artifacts/e2e-report/cli_bregress.log |
| C | cli | cli:bregress json-valid |  | . |  | NOT-RUN | not reached in this run |  |  |  |  |  |  |
| C | cli | cli:calibration_report (--estimator ppi++) | python -m agent_core.calibration_report --store $reportStore --domain-filter all --estimator ppi++ | . |  | PASS |  | 595 |  |  |  |  | artifacts/e2e-report/cli_calibration_report__--estimator_ppi___.log |
| C | cli | cli:calibration_report (wilson) | python -m agent_core.calibration_report --store $reportStore --domain-filter all | . |  | PASS |  | 520 |  |  |  |  | artifacts/e2e-report/cli_calibration_report__wilson_.log |
| C | cli | cli:eval-harness campaign analyze | python -m eval_harness.cli campaign --config $campaignYaml --store $campaignStore --mode analyze --offline --json $Report campaign_analyze.json | . |  | PASS |  | 1094 |  |  |  |  | artifacts/e2e-report/cli_eval-harness_campaign_analyze.log |
| C | cli | cli:eval-harness campaign record | python -m eval_harness.cli campaign --config $campaignYaml --store $campaignStore --mode record --offline | . |  | PASS |  | 1045 |  |  |  |  | artifacts/e2e-report/cli_eval-harness_campaign_record.log |
| C | cli | cli:eval-harness compare | python -m eval_harness.cli compare --config $compareYaml --offline --html $Report compare.html --json $Report compare.json | . |  | PASS |  | 1114 |  |  |  |  | artifacts/e2e-report/cli_eval-harness_compare.log |
| C | cli | cli:eval-harness list-plugins | python -m eval_harness.cli list-plugins | . |  | PASS |  | 1173 |  |  |  |  | artifacts/e2e-report/cli_eval-harness_list-plugins.log |
| C | cli | cli:eval-harness run | python -m eval_harness.cli run --config config/eval.example.yaml --offline | . |  | PASS |  | 1144 |  |  |  |  | artifacts/e2e-report/cli_eval-harness_run.log |
| C | cli | cli:eval-harness run --set | python -m eval_harness.cli run --config config/eval.example.yaml --set run.seed=123 --offline | . |  | PASS |  | 1098 |  |  |  |  | artifacts/e2e-report/cli_eval-harness_run_--set.log |
| C | cli | cli:merge_gate_ci | python -m agent_core.merge_gate_ci --store $mgStore --domain human --raw-confidence 0.9 --mech-pass | . |  | PASS | decision exit 10 | 534 |  |  |  |  | artifacts/e2e-report/cli_merge_gate_ci.log |
| C | cli | cli:merge_gate_context (--confidence) | python scripts/merge_gate_context.py --files src/eval_harness/x.py tests/test_x.py --confidence 0.5 --output $agentSeedJson | . |  | PASS |  | 595 |  |  |  |  | artifacts/e2e-report/cli_merge_gate_context__--confidence_.log |
| C | cli | cli:merge_seed (report store) | python -m agent_core.merge_seed --store $reportStore --change-id e2e0001 --domain agent-core --raw-confidence 0.7 | . |  | PASS |  | 571 |  |  |  |  | artifacts/e2e-report/cli_merge_seed__report_store_.log |
| C | cli | cli:proxy_eval (json) | python -m agent_core.proxy_eval --store $reportStore --domain-filter all --format json --output $proxyJson | . |  | PASS |  | 512 |  |  |  |  | artifacts/e2e-report/cli_proxy_eval__json_.log |
| C | cli | cli:proxy_eval json-valid |  | . |  | PASS |  | 0 |  |  |  |  |  |
| C | cli | cli:skill_marketplace list | python scripts/skill_marketplace.py list | . |  | PASS |  | 456 |  |  |  |  | artifacts/e2e-report/cli_skill_marketplace_list.log |
| C | cli | cli:skill_marketplace verify | python scripts/skill_marketplace.py verify | . |  | PASS |  | 605 |  |  |  |  | artifacts/e2e-report/cli_skill_marketplace_verify.log |
| C | e2e | e2e:backend-validation | python -m pytest tests --cov=backend_validation --cov-branch --cov-report=term-missing --cov-fail-under=95 --junitxml=$bvXml -p no:cacheprovider | experiments/backend-validation |  | PASS | 211 tests | 16544 | 211 | 0 | 0 | 0 | artifacts/e2e-report/e2e_backend-validation.log |
| C | e2e | e2e:skills+hooks | python -m pytest skills/architecture-drift-guard/tests/test_end_to_end.py skills/eval-corpus-forge/tests/test_end_to_end.py skills/project-setup/tests/test_gen_makefile.py skills/project-setup/tests/test_workspace.py skills/quality-gate/tests/test_gen_gate.py skills/deploy/tests/test_gen_deploy.py claude-foundation/tests/test_hooks_e2e.py -o addopts= --import-mode=importlib -p no:cacheprovider --junitxml=$e2eXml | . |  | PASS | 85 tests | 7594 | 85 | 0 | 0 | 15 | artifacts/e2e-report/e2e_skills_hooks.log |
| D | live | live:judge-anthropic | python -m eval_harness.cli run --config $cfg | . | ANTHROPIC_API_KEY | NOT-RUN | not reached in this run |  |  |  |  |  |  |
| D | live | live:judge-bedrock | python -m eval_harness.cli run --config $cfg | . | AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY | NOT-RUN | not reached in this run |  |  |  |  |  |  |
| D | live | live:judge-openai | python -m eval_harness.cli run --config $cfg | . | OPENAI_API_KEY | NOT-RUN | not reached in this run |  |  |  |  |  |  |
| D | live | live:langfuse-sink | python -m eval_harness.cli run --config $lfCfg | . | LANGFUSE_SECRET_KEY, LANGFUSE_PUBLIC_KEY, LANGFUSE_BASE_URL | NOT-RUN | not reached in this run |  |  |  |  |  |  |
| D | live | live:langfuse-smoke | python scripts/smokes/langfuse_smoke.py | . | LANGFUSE_SECRET_KEY, LANGFUSE_PUBLIC_KEY, LANGFUSE_BASE_URL | NOT-RUN | not reached in this run |  |  |  |  |  |  |
| D | live | live:phoenix-sink | python -m eval_harness.cli run --config $phCfg | . | PHOENIX_COLLECTOR_ENDPOINT | NOT-RUN | not reached in this run |  |  |  |  |  |  |
| D | live | live:phoenix-smoke | python scripts/smokes/phoenix_smoke.py | . | PHOENIX_COLLECTOR_ENDPOINT | NOT-RUN | not reached in this run |  |  |  |  |  |  |
| E | enterprise | enterprise:integration | python -m pytest tests/integration -m integration -o addopts= -p no:cacheprovider --junitxml=$entXml |  |  | NOT-RUN | not reached in this run |  |  |  |  |  |  |
| PRE | preflight-imports | preflight-imports | python -c import flow_protocol, flow_corpus, behavioral_regression, foundation_tools, agent_core, eval_harness | . |  | PASS | flow_protocol, flow_corpus, behavioral_regression, foundation_tools, agent_core, eval_harness | 0 |  |  |  |  | artifacts/e2e-report/preflight-imports.log |

## Summary

| Metric | Value |
|---|---|
| Declared steps | 40 |
| Observed steps | 30 |
| Not reached | 10 |
| Status PASS | 30 |
| Tier A | PASS 7 |
| Tier B | PASS 1 |
| Tier C | PASS 21 |
| Tier D | not exercised in this run |
| Tier E | not exercised in this run |
| Tier PRE | PASS 1 |

## Coverage Grid

| Unit | Coverage Floor (%) | Floor Anchors | CI Workflows | Suite Step | Suite Status | Tests |
|---|---|---|---|---|---|---|
| agent-core | 95 | pyproject.toml=95; quality-gate.sh=95 | agent-core-ci.yml, calibrated-merge-gate.yml | suite:agent-core | PASS | 714 |
| behavioral-regression | 95 | pyproject.toml=95; quality-gate.sh=95 | behavioral-regression-ci.yml | suite:behavioral-regression | PASS | 89 |
| claude-foundation | 85 | pyproject.toml=85; quality-gate.sh=85 | claude-foundation-ci.yml | suite:claude-foundation | PASS | 136 |
| experiments/backend-validation | 95 | pyproject.toml=95; quality-gate.sh=95 |  | e2e:backend-validation | PASS | 211 |
| flow-corpus | 95 | pyproject.toml=95; quality-gate.sh=95 | flow-corpus-ci.yml | suite:flow-corpus | PASS | 119 |
| flow-protocol | 95 | pyproject.toml=95; quality-gate.sh=95 | flow-corpus-ci.yml | suite:flow-protocol | PASS | 21 |
| root | 96 | pyproject.toml=96; quality-gate.sh=96 | architecture-drift.yml, docs.yml, eval-harness-ci.yml, merge-gate-audit.yml, merge-gate-seed.yml, merge-gate-verdict.yml, nightly-e2e.yml, outcome-labeller.yml, phoenix-live.yml, quality-gates.yml | suite:root | PASS | 995 |
| scripts | 85 | scripts/.coveragerc=85 |  | suite:scripts-gate | PASS | 995 |

## Credentials

| Live Step | Required Env Vars | Run Outcome |
|---|---|---|
| live:judge-anthropic | ANTHROPIC_API_KEY | NOT-RUN |
| live:judge-bedrock | AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY | NOT-RUN |
| live:judge-openai | OPENAI_API_KEY | NOT-RUN |
| live:langfuse-sink | LANGFUSE_SECRET_KEY, LANGFUSE_PUBLIC_KEY, LANGFUSE_BASE_URL | NOT-RUN |
| live:langfuse-smoke | LANGFUSE_SECRET_KEY, LANGFUSE_PUBLIC_KEY, LANGFUSE_BASE_URL | NOT-RUN |
| live:phoenix-sink | PHOENIX_COLLECTOR_ENDPOINT | NOT-RUN |
| live:phoenix-smoke | PHOENIX_COLLECTOR_ENDPOINT | NOT-RUN |

## Provenance

| Field | Value |
|---|---|
| Commit | 09337aec16e8b10588efd0e61c9d270d18ada1c4 |
| Branch | main |
| Generated at (UTC) | 2026-08-19T03:28:29+00:00 |
| Host | Windows-10-10.0.26200-SP0 |
| Python | 3.11.9 |
| Runner invocation | pwsh -NoProfile -File scripts/run_all_e2e.ps1 -Tiers all -HypothesisProfile ci |
| Regenerate | python tests/test_e2e_matrix.py --update |
| Policy | Generated artifact per ADR 0032/0033 - do not edit by hand. |
