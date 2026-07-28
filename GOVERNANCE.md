# Governance

This document describes how decisions are made in `ianshank/Agents`. It is
deliberately lightweight and defers to two authoritative sources: the project
charter and the Architecture Decision Records.

## Roles

- **Core maintainers** ([MAINTAINERS.md](MAINTAINERS.md), authoritative mapping in
  [.github/CODEOWNERS](.github/CODEOWNERS)) — own the roadmap, review protected
  changes, accept ADRs, and cut releases.
- **Contributors** — anyone opening issues or pull requests, under
  [CONTRIBUTING.md](CONTRIBUTING.md) and the [Code of Conduct](CODE_OF_CONDUCT.md).

The project is internally stewarded but externally visible: contributions are
welcome, while direction and the invariants stay with the core team.

## The charter is the north star

[docs/CHARTER.md](docs/CHARTER.md) defines the project's Vision, Mission, Scope
(§3, including non-goals), and Invariants (§4). Day-to-day work stays inside that
scope. Any change that would **expand scope** or **relax an invariant** is
escalated for a maintainer decision rather than implemented unilaterally
(charter §6). The charter changes rarely and only by deliberate decision; it is
drift-checked by `scripts/check_charter_drift.py`.

## How decisions are recorded

- **Architecture decisions** are captured as numbered ADRs under
  [docs/decisions/](docs/decisions/README.md). An ADR states the context, the
  decision, and its consequences. ADR numbers are not contiguous by design (the
  `0007` gap is intentional).
- **User-visible changes** are recorded in the relevant `CHANGELOG.md`.
- **Roadmap / intent** lives in `NEXT_STEPS.md`; the canonical spec is
  `HARNESS_SPEC.md`.

## Protected evaluation surface

Because this is an evaluation platform, the cheapest way to "pass" a check is to
weaken the evaluation itself. To prevent that, evaluation-defining files are
**protected paths**: changing them requires a CODEOWNER review and the
`eval-change-approved` label, enforced by `scripts/check_protected_changes.py`
against the single source of truth in `scripts/eval_protected_paths.py`. See
[CONTRIBUTING.md](CONTRIBUTING.md#protected-paths-require-a-labeled-approval).

## Changing this governance

Amendments to this document or to the charter are proposed via pull request and
accepted by the core maintainers.
