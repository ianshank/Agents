# Progress Log — langfuse-eval-harness

## 2025-06-15 — Session 002
**Features worked:** F-001, F-002
**Status changes:** F-001 todo -> done, F-002 todo -> done
**Structural changes:** Initialized harness framework (HARNESS_SPEC.md, features.yaml, schema, scripts).
**ADRs:** Added ADR-0001 (OpenAI-compatible judge design).
**Validation evidence:** `python scripts/validate.py --tier fast` exits 0.
**Next:** Seed additional features for the eval harness roadmap.

## 2025-06-15 — Session 001
**Features worked:** F-002 (OpenAI/Nemotron Integration)
**Status changes:** F-002 todo -> done
**Structural changes:** Added openai, tenacity deps. Created OpenAIJudge, config files, tests.
**ADRs:** None (pre-harness session).
**Validation evidence:** pytest --cov: 50 passed, 94% coverage.
**Next:** Integrate spec-driven harness framework.
