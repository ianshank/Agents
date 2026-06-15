# HARNESS_SPEC.md — langfuse-eval-harness

> **Canonical source of truth** for the spec-driven development harness.
> Every feature, validation gate, and progress checkpoint lives here or in the
> files this spec references.

---

## 1. Executive Intent

**langfuse-eval-harness** is a dynamic, modular, backwards-compatible enterprise LLM evaluation harness with first-class Langfuse integration. It provides a pluggable architecture for scoring LLM outputs across multiple judge backends (AWS Bedrock, OpenAI-compatible, local models), datasets, and evaluation rubrics — with full traceability piped into Langfuse for observability, analytics, and regression tracking.

The harness is designed to be local-first, test-driven, and extensible: new judges, scorers, and data sources slot in via registry patterns without touching core orchestration code.

---

## 2. Scope

### In-scope
- LLM-as-judge evaluation pipelines (multi-provider)
- Langfuse trace/score/dataset integration
- Pluggable scorer and judge registries
- Automated validation of every feature via harness scripts
- Config-driven evaluation runs (YAML/env)
- CLI and programmatic API

### Non-goals
- Cloud deployment (local-first)
- Mobile frontend

---

## 3. Architectural Invariants

These rules are enforced by lint, test, or validation scripts and **must never be
broken** without an ADR:

| # | Invariant | Enforcement |
|---|-----------|-------------|
| 1 | Dependency direction: `core` → `scorers/judges/datasets` → `sinks` | Import linter |
| 2 | No raw `print()` in production paths | Lint rule (ruff) |
| 3 | External API calls mocked in tests | Structural test |
| 4 | All judges registered via `JUDGES` registry | Plugin pattern |

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

```
langfuse-eval-harness/
├── HARNESS_SPEC.md              # This file
├── features.yaml                # Feature registry
├── features.schema.json         # JSON Schema for features.yaml
├── progress.md                  # Append-only session log
├── progress-archive/            # Rotated progress logs
│   └── .gitkeep
├── docs/
│   └── decisions/               # ADRs
│       └── 0001-openai-compatible-judge.md
├── config/                      # Evaluation configs (YAML)
├── src/
│   └── langfuse_eval_harness/   # Main package
│       ├── core/                # Orchestration, registry
│       ├── judges/              # Judge implementations
│       ├── scorers/             # Scoring functions
│       ├── datasets/            # Dataset loaders
│       └── sinks/               # Output sinks (Langfuse, file)
├── scripts/
│   ├── validate.py              # Harness validation runner
│   └── validations/             # Per-feature validation scripts
│       ├── F_001.py
│       └── F_002.py
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

---

*This spec is the single source of truth. When in doubt, read the spec.
When the spec is wrong, update it with an ADR.*
