---
name: corpus-guardian
description: Manage, verify, and synchronize the four frozen synthetic evaluation corpora (RCA, Requirements, TestGen, Answer Quality). Use whenever verifying corpus freshness, regenerating frozen synthetic fixtures, or asserting negative control invariants.
---

# Corpus Guardian — Synthetic Evaluation Corpora Management

Unified management and invariant enforcement for the four frozen synthetic evaluation corpora:
1. **RCA Corpus** (`tests/fixtures/eval/rca_corpus.jsonl` via `scripts/gen_rca_corpus.py`)
2. **Requirements Corpus** (`tests/fixtures/eval/requirements_corpus.jsonl` via `scripts/gen_requirements_corpus.py`)
3. **TestGen Corpus** (`tests/fixtures/eval/testgen_corpus.jsonl` via `scripts/gen_testgen_corpus.py`)
4. **Answer Quality Corpus** (`tests/fixtures/eval/answer_quality_corpus.jsonl` via `scripts/gen_answer_quality_corpus.py`)

## Invariants

- **Negative Control Carve-Out**: Every synthetic corpus must contain intentional negative control items with expected failure verdicts.
- **Deterministic Generation**: Generators must produce byte-identical output across repeated runs on all platforms (CRLF/LF normalized).
- **Frozen Baseline**: Corpora are never hand-edited. Any changes must occur in generator libraries (`scripts/_*_corpus_lib.py`).

## Usage

### Verify Freshness Across All Corpora
```bash
python skills/corpus-guardian/scripts/corpus_guard.py --check
```

### Regenerate All Synthetic Corpora
```bash
python skills/corpus-guardian/scripts/corpus_guard.py --generate
```

## Definition of Done

- All 4 corpora pass `--check` verification without diff or drift.
- All generators run idempotently with zero unintended git status mutations.
- Fast tier and Tier A mechanical verification pass.
