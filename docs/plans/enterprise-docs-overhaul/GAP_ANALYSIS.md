# GAP ANALYSIS — Enterprise Documentation Overhaul

> Branches scanned 2026-07-24 against `origin/main`:
> `claude/readme-docs-enterprise-update-d3ifmr` (**PR #76** — docs + metadata) and
> `claude/readme-docs-enterprise-batch-c` (**PR #77**, stacked — protected `.github`
> + `config` set). #77 is a superset of #76. Companion to [`PLAN.md`](PLAN.md).

Every "done" line was verified by a script over the working tree, not asserted.
This revision reflects the completed Batch C and the Copilot review round.

## 1. Status at a glance

| Dimension | State |
|---|---|
| Root community-health set | ✅ complete (LICENSE, NOTICE, CONTRIBUTING, SECURITY, CODE_OF_CONDUCT, SUPPORT, GOVERNANCE, MAINTAINERS) |
| Licensing / wheels | ✅ Apache-2.0; `license-files = [LICENSE, NOTICE]` and a NOTICE copy in all 7 packages — both ship in the wheel (`License-File: LICENSE` + `NOTICE`) |
| Component READMEs | ✅ **11/11** top-level dirs (incl. `config/`) |
| Package metadata | ✅ 7/7 declare `license`; 6/7 declare `[project.urls]` (backend-validation omits URLs by design) |
| Docs index + site | ✅ `docs/README.md`, ADR index, `docs/STYLE.md`; mkdocs-material site builds (non-strict) |
| `.github` templates | ✅ issue templates (bug/feature/ADR/config) + PR template (**#77**) |
| Docs CI | ✅ `docs.yml`: mkdocs build + **blocking** doc-structure guard + advisory link check (**#77**) |
| Broken relative links | ✅ 0 across 24 changed markdown files |
| Protected-path guard | #76 ✅ clean · #77 ❌ **red by design** (awaits `eval-change-approved`) |
| mkdocs `--strict` | ⚠️ deferred — cross-`docs_dir` links (by design) |
| Blanket markdownlint | ➖ intentionally dropped (legacy vendored-corpus noise; see §4) |

## 2. Verified DONE

- **11/11 component READMEs** (`config/README.md` added in #77).
- **NOTICE ships in every wheel** — `license-files` includes `NOTICE` on all 7
  pyprojects and a NOTICE copy exists in each package dir; confirmed present.
- **All community-health + `.github` intake files present** (8 root docs + 4 issue
  templates + PR template).
- **`docs.yml` reduced to the 3 meaningful jobs**: `build` (mkdocs), `guards`
  (blocking doc-structure), `links` (advisory) — all green on the latest commit.
- **0 broken relative links** across the 24 changed markdown files.
- **mkdocs build** renders the site; `agent-core` still zero-dependency (F-032).

## 3. Review round (Copilot) — resolved

**PR #76 (`214403c`):** NOTICE added to `license-files` + vendored per package (wheels
now carry attribution); `docs/STYLE.md` raw ` ```mermaid ` fence rephrased; `SUPPORT.md`
no longer dead-ends on the not-yet-existing `.github/ISSUE_TEMPLATE/`.

**PR #77 (`b65251a`→`dfcdf4f`):** docs build installs the declared `.[docs]` extra
(no version drift); doc-structure guard wrapped in try/except for bad/missing
`[project]`; PR-template `CONTRIBUTING.md` link is a full URL; markdownlint's
`|| true` mask removed, then the blanket job dropped (see §4).

## 4. Deferred BY DESIGN (not defects)

| Item | Why | Disposition |
|---|---|---|
| #77 `protected-path guard` red | `.github/**` + `config/**` are protected — the guard *must* block until a human approves | Add `eval-change-approved` |
| mkdocs `--strict` | corpus cross-links to repo-root files outside `docs_dir` | promote once the link graph is inside `docs_dir` |
| Blanket markdownlint | flagged pervasive nits in vendored `skills/*.md` this PR doesn't own (MD031/032/040/060, …) | dropped; can return scoped to cleaned dirs |

## 5. Open items (human actions, not code)

1. **Apply `eval-change-approved` to #77** → clears its protected-path guard.
2. **Merge #76**, then **retarget #77's base to `main`** (it's stacked on #76).

## 6. Optional / non-blocking (unchanged)

`docs/licenses.md` (optional-SDK license posture) · `CITATION.cff` · `RELEASING.md` ·
SPDX per-file source headers · `GAP_ANALYSIS.md` parity for flow-protocol/claude-foundation.
None block the enterprise bar.

## 7. Recommendation

Both PRs are complete for their scope and self-consistent. #76 is mergeable now
(protected-path guard clean; wheels build with Apache-2.0 + NOTICE; site builds;
links resolve). #77 is ready pending the label and the post-merge base retarget.
No code work remains — only the two human actions in §5.
