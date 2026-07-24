# experiments/

Isolated, **temporary** experiments that consume the monorepo's packages as
dependencies to answer a specific empirical question. They are deliberately
outside the main quality bar:

- Each experiment has its **own** gate (e.g. `make -C experiments/<name> check`)
  and is **not** part of `make check-all`.
- An experiment is not a package or a skill; it does not ship, and anything with
  side effects (live probes) is gated behind explicit human sign-off.
- Experiments are expected to be short-lived — promoted into a package/ADR, or
  deleted — once they have served their purpose.

## Current experiments

| Path | What it validates |
|---|---|
| [`backend-validation/`](backend-validation/README.md) | `eval-backend-validation_v1` — empirical claimed-vs-observed evidence for the eval-backend decision (Langfuse, Opik), run against real deployments. Own gate; ships unsigned. |

## Adding an experiment

Create `experiments/<name>/` with its own `pyproject.toml`, `README.md`, and gate.
Depend on the harness/packages; do **not** make the root or any package depend on
an experiment. Document the question, the method, and the exit criteria in the
experiment's README.
