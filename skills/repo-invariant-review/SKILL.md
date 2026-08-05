---
name: repo-invariant-review
description: >
  Check a change against this repository's mechanically enforced invariants — protected
  paths, the eval_harness/flow_corpus airgap, the 500-line size budget, the frozen public
  surface and plugin-registry baselines, CHARTER §4 invariant 1, and README/registry drift.
  Use before opening a PR, when reviewing someone else's change or proposal, or whenever a
  plan proposes touching core models, the engine, scorers, judges, gating, or architecture.yaml.
  Predicts concrete CI failures rather than offering style opinions.
validator_version: '2.0'
compatibility: python>=3.10
version: 1.0.0
---

# repo-invariant-review — predict CI collisions before you push

Generic peer review asks whether a change is *good*. This asks a narrower and more
falsifiable question: **would this change collide with a rule this repo already enforces?**

Every check maps to a gate that exists in CI, so a finding predicts a specific job failing —
never a matter of taste. That is what lets this skill have an honest scripted validation gate,
which `openspec-peer-review` explicitly cannot ("there is no honest scripted gate for the
quality of a peer review").

## 1. Preconditions (input contract)

- A git repository, with a base ref to diff against (default `origin/main`). Falls back to the
  working-tree diff when the base ref is unavailable.
- Python 3.10+, stdlib only. No network, no external dependencies.
- Best run from the repo root so the checks can read the repo's own sources of truth —
  `scripts/eval_protected_paths.py` and `scripts/check_size_budget.py` are read directly, so
  the skill cannot drift from the gates it predicts.

## 2. Procedure (the E2E steps)

```bash
python scripts/check_invariants.py --repo <path> --base origin/main [--has-label] [--strict] [--format {text,json}] [--out report.json]
```

1. **Run** it against the branch before pushing.
2. **Read** each finding: `BLOCKING` predicts a red CI job; `advisory` predicts future pain.
3. **Act** on the `remedy` line — each names the specific fix, not a general direction.
4. Pass `--has-label` once `eval-change-approved` is actually on the PR, so the protected-path
   finding stops masking the others.

## 3. What it checks, and what each predicts

| Check | Predicts a failure in | Typical remedy |
|---|---|---|
| `protected_paths` | the protected-path guard | request `eval-change-approved` + CODEOWNERS review, or split the PR by protection level |
| `size_budget` | `scripts/check_size_budget.py` (500-line hard fail) | move code into a submodule imported for its registration side effects |
| `airgap` | `architecture-drift-guard` (F-011, negative test F-012) | route shared code through `agent_core`; never add the edge to `architecture.yaml` |
| `surface_baselines` | `tests/test_public_surface.py` (F-039, exact equality) | `python tests/test_public_surface.py --update` |
| `registry_baselines` | `tests/test_plugin_registry_surface.py` | `python tests/test_plugin_registry_surface.py --update` |
| `core_model_change` | CHARTER §4 invariant 1 review | add a numbered ADR + a §3 Ratified Amendment (CHARTER §6) |
| `readme_registry_drift` | the `docs.yml` README/registry job | list every registered name verbatim — brace-expansion shorthand does not satisfy it |

## 4. Output contract (postconditions — what "done" means)

- A report on stdout, and at `--out` when given.
- JSON output is **byte-stable for a given input**: findings and file lists are sorted, and
  nothing carries a timestamp or an absolute path, so reports are diffable and committable.
- Exit `0` when nothing blocking was found, `1` when something was, `2` on usage error.
- `--strict` promotes advisory findings to blocking.

## 5. Validation gate (before declaring success)

Unlike a subjective review skill, this one has a real gate:

```bash
python scripts/validate_skill.py --skill . --tier standard
```

The evals in `evals/evals.json` run the checker against committed fixtures — one clean tree and
one that violates several invariants at once — and assert both the exit code and the specific
findings. A check that silently stops firing fails the eval.

## 6. Limits worth knowing

- It predicts *collisions*, not correctness. A change can pass every check here and still be
  wrong; run the full quality gate as well.
- `core_model_change` is satisfied by *any* ADR in the same diff. It cannot tell whether the ADR
  actually authorises the change — that judgement stays human.
- `surface_baselines` and `registry_baselines` are advisory because not every `src/` change adds
  an export. They flag the risk; only the real guard knows.

## 7. Examples

See `evals/evals.json` and its fixtures for the exact invocations and expected findings.
