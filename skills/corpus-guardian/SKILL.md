---
name: corpus-guardian
version: 1.0.0
description: Manage, verify, and synchronize the four frozen synthetic evaluation corpora (RCA, Requirements, TestGen, Answer Quality). Use whenever verifying corpus freshness, regenerating frozen synthetic fixtures, or asserting negative control invariants.
---

# Corpus Guardian — Synthetic Evaluation Corpora Management

Unified management and invariant enforcement for the four frozen synthetic evaluation corpora:
1. **RCA Corpus** (`corpora/rca/v1/` via `scripts/gen_rca_corpus.py`)
2. **Requirements Corpus** (`corpora/requirements/v1/` via `scripts/gen_requirements_corpus.py`)
3. **TestGen Corpus** (`corpora/testgen/v1/` via `scripts/gen_testgen_corpus.py`)
4. **Answer Quality Corpus** (`corpora/answer_quality/v1/` via `scripts/gen_answer_quality_corpus.py`)

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
