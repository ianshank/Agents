# Contributing to agent-core

`agent-core` lives in the `ianshank/Agents` monorepo as the self-contained
`agent-core/` subfolder. The harness at the repo root is a **separate package** —
do not entangle the two.

## Dev loop — run everything from `agent-core/`

```bash
cd agent-core
pip install -e ".[dev]"     # editable install + pinned toolchain (zero runtime deps)
python -m pytest --cov      # branch coverage gated at 95%
ruff check agent_core tests
ruff format --check agent_core tests
mypy agent_core             # strict (library only; tests are relaxed)
```

The `attr:`-based dynamic version resolves against this directory, so the editable
install **must** be run with `agent-core/` as the working directory.

## Testing practices

- **TDD:** write the failing test first, then the minimal implementation, then commit.
- **Property tests** use Hypothesis; example counts come from the `dev` (50) / `ci` (500)
  profiles via `HYPOTHESIS_PROFILE`, never hard-coded per test.
- **Deterministic, offline:** no network; deterministic test doubles, not mocks of core logic.
- **Coverage honesty:** a defensive guard unreachable by meaningful input gets
  `# pragma: no cover` with a reason — never a padding test (see `GAP_ANALYSIS.md` §5).
- **No hard-coded values:** every threshold/constant lives in a validated `*Config` field.

## Pre-commit (optional, scoped to agent-core)

```bash
pre-commit run --all-files --config agent-core/.pre-commit-config.yaml
```

## CI

`.github/workflows/agent-core-ci.yml` runs on changes under `agent-core/**` across
Python 3.10 / 3.11 / 3.12: ruff lint + format check, strict mypy, and pytest with the
95% coverage gate under the `ci` Hypothesis profile.
