# GAP ANALYSIS — Enterprise Documentation Overhaul

> Branch: `claude/readme-docs-enterprise-update-d3ifmr`. Scanned 2026-07-24
> against `origin/main`. Scope: documentation, licensing, packaging metadata, and
> repository organization. Companion to [`PLAN.md`](PLAN.md).

This records what the branch **delivers**, what is **deliberately deferred**, and
what remains **open** — measured, not asserted. Every "done" line below was
verified by a script over the working tree, not from memory.

## 1. Status at a glance

| Dimension | State |
|---|---|
| Root community-health set | ✅ complete (LICENSE, NOTICE, CONTRIBUTING, SECURITY, CODE_OF_CONDUCT, SUPPORT, GOVERNANCE, MAINTAINERS) |
| Licensing | ✅ Apache-2.0 at root + 6 per-wheel copies; PEP 639 metadata on all 7 pyprojects |
| Component READMEs | ✅ 10/11 top-level dirs (only `config/` deferred — protected path) |
| Docs index + site | ✅ `docs/README.md`, ADR index, `docs/STYLE.md`, mkdocs-material site (non-strict) |
| Root README / AGENTS map | ✅ restructured additively; doc-map extended |
| Protected-path CI/templates (Batch C) | ⛔ not started — needs `eval-change-approved` label (separate PR) |
| mkdocs `--strict` | ⚠️ deferred — 48 cross-`docs_dir` link warnings (by design, R6) |
| Broken relative links | ✅ 0 across 21 changed markdown files |
| Protected-path guard | ✅ clean — no eval-defining path touched |

## 2. Verified DONE (with evidence)

- **All package metadata present.** 7/7 pyprojects declare `license`
  (SPDX `Apache-2.0`), `readme`, `classifiers`; 6/7 declare `[project.urls]`
  (backend-validation intentionally omits URLs). Isolated `pip wheel` of
  `flow-protocol` and the root package emit `License-Expression: Apache-2.0` +
  `License-File: LICENSE` (Metadata-Version 2.4).
- **`agent-core` stays zero-runtime-dependency** — the F-032 invariant is intact
  (no `[project].dependencies` key added).
- **10 of 11 top-level component dirs have a README** — the one gap (`config/`) is
  deferred on purpose (see §3).
- **Docs render.** `mkdocs build` succeeds and produces `site/index.html`.
- **No broken relative links** in any of the 21 changed/new markdown files.

## 3. Deferred BY DESIGN (not defects)

| Item | Why deferred | Where it lands |
|---|---|---|
| `config/README.md` | `config/**` is a **protected path** — adding a file there needs the `eval-change-approved` label. `config/` is instead summarized in `docs/README.md`. | Batch C (labeled PR) |
| `.github/ISSUE_TEMPLATE/`, `.github/pull_request_template.md` | `.github/**` is protected | Batch C |
| `.github/workflows/docs.yml` (mkdocs build/deploy) | `.github/**` is protected | Batch C |
| Doc-quality guards (link-check, "every component has a README", "every package declares a license") | Implemented as **workflow steps**, not `scripts/*.py`, to avoid the ≥85% `scripts/` coverage floor and new protected `tests/**` (R5) | Batch C |
| `mkdocs --strict` | The existing 40-file corpus cross-links to repo-root files outside `docs_dir` (48 warnings). Enabling strict now would fail the build. | Follow-up once the link graph is brought inside `docs_dir` or a monorepo/include plugin is added |
| `experiments/backend-validation` `[project.urls]` | It is temporary/isolated and "ships unsigned"; `license` added for consistency, URLs skipped | n/a (intentional) |

## 4. Open items resolved on this scan

- **Stale committed `PLAN.md`.** The first commit (`0630afd`) captured the
  *pre-decision* draft (license "recommended", mkdocs "optional", an open-questions
  section). It has been **reconciled** to the locked decisions (Apache-2.0, hybrid
  audience, mkdocs site) and the two-PR structure in this same change.

## 5. Optional / nice-to-have (not blocking enterprise bar)

| Item | Value | Recommendation |
|---|---|---|
| `docs/licenses.md` or an expanded NOTICE enumerating optional-SDK licenses | Enterprise redistribution hygiene for the `langfuse`/`openai`/`anthropic`/`boto3`/`phoenix`/`braintrust`/`autoevals` extras | Add in Batch C or a follow-up; current NOTICE names them generically |
| `CITATION.cff` | Research-adjacent citability | Low priority; add if the project is cited |
| `RELEASING.md` | Documents the keep-a-changelog + single-sourced-version release flow | Nice-to-have; content already implicit in `AGENTS.md` |
| SPDX license headers in `.py` source | Per-file provenance | Large mechanical change; defer unless required by policy |
| `GAP_ANALYSIS.md` for `flow-protocol` / `claude-foundation` | Parity with the other 3 packages | Low value — `flow-protocol` is trivial/100%-covered; `claude-foundation` uses `docs/adr/` + `CLAUDE.md`. Leave as-is. |
| Root README coverage/CI badges | The coverage badge is static; the CI badge points only at `eval-harness-ci.yml` | Cosmetic; refine when the docs workflow exists |

## 6. Risks carried forward (from the design review)

- **R1 (setuptools≥77 / PEP 639)** — resolved: build-system pins bumped; isolated
  wheels verified. Watch that no contributor reverts a pin to `>=68`.
- **R2 (readme= before README exists)** — resolved by shipping metadata + READMEs
  in one PR. If packages are ever split, keep them together.
- **R6 (mkdocs strict)** — carried as the deferred item above.

## 7. Recommendation

PR 1 (this branch) is **complete and self-consistent** for the unprotected scope
and safe to merge (protected-path guard clean, wheels build, site builds, links
resolve). The only enterprise items still open are the **protected Batch C** set,
which is correctly held for a separate labeled PR. Nothing in §5 blocks the
enterprise-documentation bar.
