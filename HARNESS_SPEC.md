# HARNESS_SPEC.md — root `eval_harness` package feature/validation process

> **Canonical source of truth for the feature/validation process** described
> below (the `features.yaml` registry, the `F_XXX.py` validation-script
> contract, ADR conventions, progress tracking). For repo-wide scope, the
> 5-package mission, and the CI-enforced invariants, the charter at
> [docs/CHARTER.md](docs/CHARTER.md) is canonical — this spec describes how
> the root `eval_harness` package applies that process day to day, not the
> other packages' scope or invariants.

---

## 1. Executive Intent

**langfuse-eval-harness** (root `eval_harness`, one of five packages in this
monorepo — see [docs/CHARTER.md](docs/CHARTER.md) §2 for the full mission and
the other four: `agent-core`, `behavioral-regression`, `flow-corpus`,
`flow-protocol`) is the LLM evaluation harness itself: a pluggable engine for
scoring LLM outputs across multiple judge backends (AWS Bedrock,
OpenAI-compatible, Anthropic), datasets, and evaluation rubrics, with
first-class Langfuse and Phoenix integration for observability, analytics, and
regression tracking.

The harness is offline-first, test-driven, and extensible: new judges,
scorers, sinks, datasets, and targets slot in via registry patterns without
touching core orchestration code.

---

## 2. Scope

This section describes the root `eval_harness` package specifically. For the
repo-wide scope (all 5 packages) and the ratified, additive scope amendments,
see [docs/CHARTER.md](docs/CHARTER.md) §3.

### In-scope
- LLM-as-judge evaluation pipelines (multi-provider)
- Langfuse and Phoenix trace/score/dataset integration (SDK-optional seams)
- Pluggable scorer, judge, sink, dataset, and target registries
- Automated validation of every feature via harness scripts
- Config-driven evaluation runs (YAML/env)
- CLI and programmatic API

### Non-goals
See [docs/CHARTER.md](docs/CHARTER.md) §3 for the full, current list (not a
training/fine-tuning pipeline, gates never run live evaluations, no
permissive config parsing, the offline suite depends on nothing external,
and more) — that list is charter-governed and the canonical one.

---

## 3. Architectural Invariants

The 7 CI-enforced, repo-wide invariants are defined in
[docs/CHARTER.md](docs/CHARTER.md) §4 (open/closed extensibility via
registries, versioned/backward-compatible config, Protocol-based DI, narrow
I/O seams, config-driven values, non-negotiable quality gates, no secrets).
This package applies them via the specific mechanisms below:

| Charter invariant | How `eval_harness` enforces it |
|---|-----------|
| Open/closed extensibility | Judges, scorers, sinks, datasets, and targets register via `eval_harness.plugins`' `SCORERS`/`JUDGES`/`SINKS`/`DATASETS`/`TARGETS` registries — never by editing the engine |
| No raw `print()` in production paths | Lint rule (ruff) |
| External API calls mocked in tests | Full offline deterministic matrix coverage (`tests/test_matrix_eval_tools.py`) |
| Dependency-direction discipline | `architecture.yaml` + `skills/architecture-drift-guard` (grimp-based import-graph diff, CI-enforced) |

---

## 4. Feature Registry

All features are tracked in **`features.yaml`** (validated by `features.schema.json`).

### Feature lifecycle

```
todo ──► in_progress ──► done
  │          │              │
  ▼          ▼              ▼
blocked    blocked        (terminal)
  │
  ▼
deferred
```

### Key fields

| Field | Purpose |
|-------|---------|
| `id` | Unique, e.g. `F-001` |
| `epic` | Grouping label |
| `category` | `functional`, `non-functional`, `infrastructure`, `validation` |
| `priority` | `critical` > `high` > `medium` > `low` |
| `status` | See lifecycle above |
| `tier` | `fast` (unit/mock), `slow` (integration), `hardware` (GPU) |
| `verification` | Human-readable acceptance criteria |
| `validation_command` | Exact command to prove the feature works |
| `implemented_in` | Git SHA when feature was completed |
| `depends_on` | List of prerequisite feature IDs |

### Schema enforcement

```bash
# Validate features.yaml against the JSON schema
python scripts/validations/validate_schema.py
```

---

## 5. Validation Harness

### Directory layout

```
scripts/
├── validate.py            # Main entry point — runs all or filtered validations
└── validations/
    ├── __init__.py
    ├── F_001.py            # Harness initialized
    ├── F_002.py            # OpenAI-compatible LLM judge
    └── ...                 # One script per feature
```

### Running validations

```bash
# Run all validations
python scripts/validate.py

# Run only fast-tier validations
python scripts/validate.py --tier fast

# Run a single feature validation
python scripts/validations/F_001.py
```

### Validation script contract

Every `F_XXX.py` script **must**:

1. Exit `0` on success, non-zero on failure.
2. Print a single summary line: `PASS: F-XXX — <name>` or `FAIL: F-XXX — <reason>`.
3. Be idempotent — safe to run repeatedly.
4. Not require network access for `fast` tier.

### Adding a new feature

1. Add the feature to `features.yaml` with `status: todo`.
2. Create `scripts/validations/F_XXX.py` (can start as a stub that exits 1).
3. Implement the feature.
4. Update `status: done`, set `implemented_in` to the commit SHA, and set `validation_command`.
5. Run `python scripts/validate.py` to confirm green.

---

## 6. Progress Tracking

### progress.md (append-only log)

Each development session appends a block to `progress.md`:

```markdown
## YYYY-MM-DD — Session NNN
**Features worked:** F-XXX, F-YYY
**Status changes:** F-XXX todo -> done
**Structural changes:** <summary>
**ADRs:** Added ADR-NNNN (title).
**Validation evidence:** `python scripts/validate.py --tier fast` exits 0.
**Next:** <what comes next>
```

### progress-archive/

When `progress.md` exceeds ~200 lines, the oldest sessions are moved to
`progress-archive/YYYY-MM.md`. The `progress-archive/.gitkeep` ensures the
directory is tracked.

---

## 7. Decision Records (ADRs)

ADRs live in `docs/decisions/` and follow the format:

```
NNNN-short-title.md
```

Each ADR contains:

```markdown
# ADR-NNNN — Title
**Status:** proposed | accepted | deprecated | superseded
**Context:** Why this decision was needed.
**Decision:** What was decided.
**Consequences:** Trade-offs and impacts.
**Related features:** F-XXX, F-YYY
```

---

## 8. Tooling

| Tool | Version / Notes |
|------|-----------------|
| Python | 3.10+ |
| Package management | pip / setuptools |
| Testing | pytest + pytest-cov |
| Linting | ruff |
| Type checking | mypy |
| Version control | git |
| Config parsing | pyyaml |
| Data validation | pydantic |
| LLM SDK | openai SDK (optional) |
| Retry logic | tenacity (optional) |

---

## 9. Repository Structure

The root `eval_harness` package's own layout (the piece this spec's
feature/validation process governs). This monorepo has 4 sibling packages
alongside it — `agent-core/`, `behavioral-regression/`, `flow-corpus/`,
`flow-protocol/` — plus `claude-foundation/` and top-level `docs/`, `skills/`,
`scripts/`; see [docs/CHARTER.md](docs/CHARTER.md) §2 and the repo root for
those:

```
Agents/                          # repo root
├── HARNESS_SPEC.md              # This file (eval_harness feature/validation process)
├── docs/CHARTER.md              # Canonical: mission, scope, invariants (all 5 packages)
├── features.yaml                # Feature registry (eval_harness)
├── features.schema.json         # JSON Schema for features.yaml
├── progress.md                  # Append-only session log
├── progress-archive/            # Rotated progress logs
│   └── .gitkeep
├── docs/
│   ├── decisions/                # ADRs (0001 onward — see the index there)
│   ├── SKILL_TEMPLATE.md         # Reference template for skills
│   └── SKILL_VALIDATION_TEMPLATE.md # Reference validator details
├── config/                      # Evaluation configs (YAML)
├── src/
│   └── eval_harness/            # Root package
│       ├── core/                 # Orchestration, registry, interfaces
│       ├── judges/               # Judge implementations
│       ├── scorers/              # Scoring functions
│       ├── datasets/             # Dataset loaders (inline, jsonl, csv, parquet, langfuse, braintrust)
│       ├── targets/              # System-under-test adapters (echo, callable, model-backed)
│       ├── langfuse_client/      # Langfuse integration (SDK-optional seam)
│       ├── phoenix_client/       # Arize Phoenix integration (SDK-optional seam)
│       ├── braintrust_client/    # BrainTrust integration (SDK-optional seam)
│       └── sinks/                # Output sinks (console, json, html, langfuse, phoenix, braintrust)
├── scripts/
│   ├── validate.py              # Harness validation runner
│   ├── validate_skill.py        # Skill validator runner
│   ├── validations/             # Per-feature validation scripts (F_001.py onward)
│   └── check_*.py               # Quality gates (charter drift/invariants, size budget, protected paths, ...)
├── skills/                      # Registered skill modules (marketplace.yaml)
├── tests/                       # pytest test suite
├── examples/                    # Usage examples
├── pyproject.toml               # Project metadata and deps
└── README.md
```

---

## 10. Conventions

### Naming
- Feature IDs: `F-NNN` (zero-padded, monotonically increasing)
- Validation scripts: `F_NNN.py` (underscores, matching feature ID)
- ADRs: `NNNN-kebab-case-title.md`
- Python packages: `snake_case`
- Classes: `PascalCase`

### Commit messages
```
feat(F-NNN): short description
fix(F-NNN): what was fixed
docs: update progress.md, ADRs
harness: structural changes to the harness itself
```

### Branch strategy
- `main` — stable, all validations green
- `feat/F-NNN-short-name` — feature branches
- `fix/F-NNN-short-name` — bugfix branches

---

## 11. Bootstrap Checklist

- [x] `HARNESS_SPEC.md` exists and is parseable
- [x] `features.yaml` exists and validates against `features.schema.json`
- [x] `features.schema.json` exists (JSON Schema draft 2020-12)
- [x] `scripts/validate.py` exists and runs
- [x] `progress.md` initialized
- [x] `progress-archive/.gitkeep` exists
- [x] `docs/decisions/` directory exists with ADR-0001
- [x] F-001 validation passes
- [x] F-002 validation passes
- [x] F-003 validation passes
- [x] F-004 validation passes
- [x] F-005 validation passes

---

## 12. Skill Framework & Langfuse Integration

### Skill Directory Convention
Each skill resides in a self-contained directory under `skills/` with the following structure:
```
skills/<skill-name>/
├── SKILL.md                 # Core instructions and metadata
├── evals/
│   ├── evals.json           # Test cases with structural and behavioral assertions
│   └── fixtures/            # Test fixture files
├── references/              # Local documentation and references
└── scripts/
    ├── run.py               # E2E executable script wrapper for the skill
    └── validate_skill.py    # Local validator script (copy of central validator)
```

### validate_skill.py Usage
Skills are validated using `scripts/validate_skill.py`. It has two tiers:
- **Structural**: Ensures `SKILL.md` conforms to the template structure, has no unreplaced placeholders, and complies with constraints (e.g. length under 500 lines). Graded by the `ASSERTION_GRADERS` registry for full extensibility.
- **Behavioral**: Executes commands from `evals.json` offline using python scripts and asserts properties such as exit codes, output contents, and file existence, powered by the modular registry pattern.

Run the validator with:
```bash
python scripts/validate_skill.py --skill skills/openai-judge --tier structural,behavioral
```

### Langfuse Tracing & Credentials
When Langfuse tracing is enabled, the harness instruments runs with
`@observe()` decorators and links dataset run items. Per charter §4 invariant
7, credentials are sourced from environment variables only, with no hardcoded
default values anywhere in source — see [.env.example](.env.example) for the
canonical set (`LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`,
`LANGFUSE_BASE_URL`, the last defaulting to the public
`https://us.cloud.langfuse.com` endpoint, which is not a secret). When the
`langfuse` library is not installed, or the secret/public keys are unset,
tracing gracefully falls back to a no-op mode without interrupting harness
execution.

---

*This spec is the single source of truth. When in doubt, read the spec.
When the spec is wrong, update it with an ADR.*

