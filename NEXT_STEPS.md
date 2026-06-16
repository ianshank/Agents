# Next Steps

## Immediate (Pre-v1.2.0)

- [ ] **Rotate Leaked Credentials** — The Langfuse keys `sk-lf-e220d788...` and
  `pk-lf-ad617cfc...` were committed in git history. Rotate them in the Langfuse
  dashboard and update `.env` files.
- [ ] **Pin Vulnerable Dependencies** — Upgrade `urllib3>=2.7.0`, `idna>=3.15`,
  `pygments>=2.20.0`, `requests>=2.33.0` per Snyk scan results.
- [ ] **Enable Snyk Code (SAST)** — Upgrade the Snyk org plan to enable static
  analysis of Python source code.
- [ ] **BedrockJudge Tests** — Add mocked boto3 tests (similar to OpenAIJudge
  pattern) to close the last coverage gap.

## Short Term (v1.2.0)

- [ ] **CI/CD Pipeline** — GitHub Actions workflow for test, lint, type-check,
  and Snyk scan on every PR.
- [ ] **Dynamic Version** — Use `setuptools.dynamic.version` to derive version
  from `version.py` and eliminate duplication in `pyproject.toml`.
- [ ] **Parallel Execution** — Add `asyncio`/`concurrent.futures` option to
  `EvalEngine` for large datasets.
- [ ] **CSV/Parquet Dataset Source** — Extend dataset support beyond JSONL/inline.
- [ ] **`py.typed` Marker** — Ship PEP 561 marker for downstream type checkers.

## Medium Term (v1.3.0)

- [ ] **Skill Marketplace** — Centralized registry for community-contributed
  skills with versioned SKILL.md validation.
- [ ] **Weighted/Ensemble Scoring** — Support composite scores from multiple
  scorers with configurable weights.
- [ ] **Dashboard Export** — Rich HTML report generation from `RunResult`.
- [ ] **Rate Limit Budget** — Configurable token/request budgets for judge calls.

## Long Term

- [ ] **Multi-model Comparison** — Run the same dataset against multiple models
  and produce comparative reports.
- [ ] **A/B Eval Campaigns** — Persistent eval campaigns with statistical
  significance testing.
- [ ] **Langfuse Prompt Management** — Pull judge prompts from Langfuse prompt
  registry instead of config YAML.
