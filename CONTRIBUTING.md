# Contributing

Thanks for your interest in improving this project. This repository
(`ianshank/Agents`) is a **monorepo** of five installable Python packages plus a
vendored skills marketplace, operational tooling, and CI. It is developed in the
open (externally visible) but stewarded by a core team; see
[GOVERNANCE.md](GOVERNANCE.md) and [MAINTAINERS.md](MAINTAINERS.md).

Before you start, skim two orientation docs:

- [README.md](README.md) — install / run / test / the requirement→mechanism map.
- [AGENTS.md](AGENTS.md) — the authoritative "which doc answers what" map and the
  non-negotiable constraints every change must respect.
- [docs/CHARTER.md](docs/CHARTER.md) — the north-star scope (§3) and invariants
  (§4). Work that would expand scope or relax an invariant is escalated, not
  implemented unilaterally.

## Repository layout

| Path | Package / role | Dev command runs from |
|---|---|---|
| `src/eval_harness/` | `langfuse-eval-harness` (root package) | repo root |
| `agent-core/` | `agent-core` | `agent-core/` |
| `behavioral-regression/` | `behavioral-regression` | `behavioral-regression/` |
| `flow-corpus/` | `flow-corpus` | `flow-corpus/` |
| `flow-protocol/` | `flow-protocol` | `flow-protocol/` |
| `claude-foundation/` | `claude-foundation-tools` | `claude-foundation/` |
| `skills/` | vendored skills (registered in `skills/marketplace.yaml`) | repo root |
| `scripts/` | feature validators + CI guards | repo root |

Each package is independently built and tested with its **own** coverage floor.
Do not entangle packages; cross-package dependencies go through the declared
seams (see `architecture.yaml` and `docs/c4_architecture.md`).

## Dev loop

Root package:

```bash
pip install -e '.[dev]'              # editable install + pinned toolchain
./scripts/quality-gate.sh all        # lint + format-check + mypy + pytest --cov
make check                           # same, via the generated Makefile
make check-all                       # root gate + every sibling package's gate
```

A sibling package (example — `agent-core`):

```bash
cd agent-core
pip install -e '.[dev]'
python -m pytest --cov               # branch coverage gated at 95%
ruff check agent_core tests
ruff format --check agent_core tests
mypy agent_core
```

Every package and skill enforces a **≥95% branch-coverage floor** (the root
harness gate is 96%; the quality-gate tooling stays at 85%). Operational scripts
under `scripts/` carry their own **≥85%** gate (`scripts/.coveragerc`).

## Testing practices

- **TDD:** write the failing test first, then the minimal implementation.
- **Deterministic, offline:** the default suite runs with no network and no live
  SDKs — deterministic test doubles, not mocks of core logic.
- **Coverage honesty:** a defensive guard unreachable by meaningful input gets a
  `# pragma: no cover` with a reason, never a padding test.
- **No hard-coded values:** every threshold/constant lives in a validated
  `*Config` field with the default documented on the field.

## Non-negotiable constraints (enforced by CI)

These are summarized here and stated authoritatively in
[AGENTS.md](AGENTS.md#non-negotiable-constraints):

- No hard-coded secrets, absolute paths, or production URLs in source —
  credentials come from environment variables (see [.env.example](.env.example)).
- `SCHEMA_VERSION` is single-sourced; bumps happen in dedicated release commits
  with migration code.
- `from_dict` is strict — unknown keys raise; do not add permissive fallbacks.

## Protected paths (require a labeled approval)

Some paths define the **evaluation surface** of the harness. Changing them can
silently weaken what the harness measures, so CI (`scripts/check_protected_changes.py`)
requires a human-reviewed `eval-change-approved` label. The single source of
truth is [`scripts/eval_protected_paths.py`](scripts/eval_protected_paths.py); it
currently covers:

- `features.yaml`, `features.schema.json`, `architecture.yaml`
- `config/**`
- `src/eval_harness/{gating,scorers,judges}/`
- `scripts/validations/**`
- `tests/**` (any new `tests/test_*.py`)
- `.github/**`

If your change touches one of these, expect a CODEOWNER review and the label.

## Adding things

- **A new scorer / judge / sink / dataset / target:** register it via the
  `Registry` / entry-point seam — no core edits. See the "Extend" section of the
  [README](README.md#extend-no-core-changes).
- **A new skill:** follow [docs/SKILL_TEMPLATE.md](docs/SKILL_TEMPLATE.md), add it
  to `skills/marketplace.yaml`, and validate with
  `python scripts/skill_marketplace.py validate`. See [skills/README.md](skills/README.md).
- **An architectural decision:** add a numbered ADR under `docs/decisions/`
  (see [docs/decisions/README.md](docs/decisions/README.md) for the convention;
  the `0007` gap is intentional — do not backfill it).
- **A user-visible change:** add an entry to the relevant `CHANGELOG.md`
  (keep-a-changelog format) and update `architecture.yaml` + regenerate
  `architecture.mmd` if you added/removed a component or import edge.

## Commits & pull requests

- Branch off the default branch; keep commits focused with descriptive messages.
- Run `make check-all` locally before opening a PR.
- Open the PR as a draft until CI is green; fill in the PR template.
- One logical change per PR. Keep protected-path changes in their own PR so an
  unrelated docs or feature PR does not need the `eval-change-approved` label.

## Code of Conduct

Participation is governed by our [Code of Conduct](CODE_OF_CONDUCT.md).

## License

By contributing, you agree that your contributions are licensed under the
[Apache License 2.0](LICENSE), the license of this project.
