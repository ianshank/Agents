# GAP ANALYSIS — Enterprise Documentation Overhaul

> Scanned 2026-07-24 against `origin/main` (`e8f2b40`). Companion to
> [`PLAN.md`](PLAN.md). Every "done" line below was verified by running the
> repo's own gates or by a script over the tree — not asserted.

## 1. Status at a glance

| Dimension | State |
|---|---|
| Licensing (Apache-2.0) | ✅ on `main` — `LICENSE` + `NOTICE` + per-wheel copies; PEP 639 metadata on all 7 pyprojects (`license-files = [LICENSE, NOTICE]`) |
| Root community-health set | ✅ on `main` — CONTRIBUTING, SECURITY, CODE_OF_CONDUCT, SUPPORT, GOVERNANCE, MAINTAINERS |
| Component READMEs | ✅ 11/11 top-level dirs (`config/README.md` lands with **this** PR) |
| Docs index + ADR index + STYLE | ✅ on `main` |
| mkdocs-material site | ✅ on `main` (non-strict) |
| `.github` issue/PR templates | ✅ **this PR** |
| Docs CI (`docs.yml`) | ✅ **this PR** — mkdocs build + blocking doc-structure guard + advisory link check |
| Backends/Opik clarity in README | 🔄 open in a separate PR (README "Backends and integrations" matrix) |
| mkdocs `--strict` | ⚠️ deferred — corpus cross-links outside `docs_dir` |
| Blanket markdownlint | ➖ intentionally dropped (legacy vendored-corpus noise) |

## 2. Quality gates — measured, all green

`make check-all` run on 2026-07-24 with the pinned toolchain
(`ruff 0.15.20`, `mypy 2.1.0`, `pytest 9.1.1`), all 5 member packages installed
editable, and every optional SDK extra present. **6/6 package gates PASS, 0 test
failures**:

| Package | Floor | Measured coverage | Lint / Type |
|---|---|---|---|
| root (`eval_harness`) | 96% | **97.55%** | ruff ✓ · format ✓ (479 files) · mypy ✓ |
| root `scripts/` gate | 85% | **95.85%** | — |
| `agent-core` | 95% | **98.78%** | ruff ✓ · mypy ✓ |
| `behavioral-regression` | 95% | **100.00%** | ruff ✓ · mypy ✓ |
| `claude-foundation` | 85% | **96.03%** | ruff ✓ · mypy ✓ |
| `flow-corpus` | 95% | **100.00%** | ruff ✓ · mypy ✓ |
| `flow-protocol` | 95% | **100.00%** | ruff ✓ · mypy ✓ |

This confirms the documentation + packaging-metadata work introduced **no
regression**: no runtime `.py` changed, `agent-core` keeps zero runtime
dependencies (F-032), and every `__all__` public-surface baseline still matches.

## 3. Deferred BY DESIGN (not defects)

| Item | Why | Disposition |
|---|---|---|
| `protected-path guard` red on this PR | `.github/**` + `config/**` are protected — the guard *must* block until a human approves | apply `eval-change-approved` |
| mkdocs `--strict` | 40-file corpus cross-links to repo-root files outside `docs_dir` | promote once the link graph is inside `docs_dir` |
| Blanket markdownlint job | flagged pervasive pre-existing nits across vendored `skills/*.md` this work doesn't own | dropped; can return scoped to cleaned dirs |
| `experiments/backend-validation` `[project.urls]` | temporary, isolated, ships unsigned | intentional |

## 4. Known tech debt / follow-ups

1. **Registry-name drift (the live risk).** Component names (sinks, judges,
   datasets, targets, scorers) are enumerated in three unguarded places: the root
   README Layout block, the root README backends matrix, and
   `src/eval_harness/README.md`. Nothing mechanically keeps them in sync with the
   `@REGISTRY.register(...)` calls that own them. A drift check comparing the
   registries to the READMEs is the durable fix — **deliberately not added here**,
   because both README copies are corrected in the separate backends PR and the
   check would be red until that merges. File it once that lands.
2. **Doc-quality checks are workflow steps, not `scripts/*.py`** — by design, to
   avoid the ≥85% `scripts/` coverage floor and new protected `tests/**`. The
   trade-off is they are not unit-tested; they are simple and fail loudly.
3. **Advisory link check** is `continue-on-error` (soak mode). Promote to blocking
   once the corpus is clean.
4. **Optional, non-blocking:** `docs/licenses.md` enumerating optional-SDK
   licenses; `CITATION.cff`; `RELEASING.md`; SPDX per-file source headers.

## 5. Recommendation

With this PR the enterprise-documentation programme is **functionally complete**:
licensing, community health, component READMEs, docs IA + site, and now the
`.github` intake templates plus a blocking doc-structure guard in CI. The gates
are measured green across all six packages. The single meaningful piece of debt
left is the registry-name drift check (§4.1), which is sequenced behind the
backends-README PR.
