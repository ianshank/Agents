---
name: architecture-drift-guard
description: Detect and block architecture drift in CI by comparing a codebase's actual Python import graph against a declared C4 component model. Use this whenever the user wants to enforce architecture in CI/CD, fail builds on undocumented dependencies, keep C4/Mermaid diagrams in sync with code, set up architecture tests or fitness functions, prevent layering violations, or guard/lint/gate their architecture — even if they don't name C4 or Mermaid explicitly. Also use it to bootstrap an architecture manifest from an existing repo or to remediate a failing drift check.
compatibility: python>=3.10, grimp, pyyaml
version: 1.0.0
---

# Architecture Drift Guard — E2E Action Skill

Keep a codebase's real structure honest against its documented architecture and
fail CI when they diverge. The architecture is declared once in a manifest
(`architecture.yaml`); the Mermaid C4 diagram and the CI gate are both derived
from it. **The blocking gate is deterministic code — a model is never in its
decision path.** Same inputs always yield the same exit code; that
reproducibility is the entire value.

Scope: this enforces the **C4 Component level** (packages/modules and their
edges) for **Python** (grimp parses Python imports). Edges are **direct, not
transitive**. Context (L1) and Container (L2) are human-defined and not derivable
from code — do not promise drift detection there.

## 1. Preconditions (input contract)

- An `architecture.yaml` manifest exists with `schema_version`, `root_packages`,
  and `components`; `dependencies` may be empty when bootstrapping.
- The `root_packages` are importable — installed, or reachable via the manifest's
  `sys_path` entries (which the runner prepends to `sys.path`).
- `grimp` and `pyyaml` are installed (`pip install grimp pyyaml`).

If any precondition fails the runner stops and reports it (exit 2) — it does not
improvise around a broken manifest.

## 2. Procedure (the E2E steps)

Deterministic work lives in `scripts/`; the library is `scripts/adguard/` and the
two thin entrypoints call it.

1. **Bootstrap** the declared edges from reality, then review them WITH the user
   (undocumented edges are exactly the drift to surface — don't launder them):
   ```bash
   python scripts/drift_check.py --manifest architecture.yaml --emit-actual
   ```
   Paste the reviewed `dependencies:` block into the manifest.
2. **Generate** the diagram and commit both files:
   ```bash
   python scripts/mermaid_gen.py --manifest architecture.yaml -o architecture.mmd
   ```
3. **Gate** in CI — run both checks on every PR:
   ```bash
   python scripts/drift_check.py --manifest architecture.yaml          # drift gate
   python scripts/mermaid_gen.py --manifest architecture.yaml --check -o architecture.mmd  # freshness gate
   ```

## 3. Output contract (postconditions — what "done" means)

- `drift_check.py` exits **0** when every actual component edge is declared,
  **1** when an undocumented edge exists (drift), **2** on a manifest/extraction
  error. Undocumented edges are printed by name; declared-but-unused edges are a
  `[warn]` only and never fail.
- `mermaid_gen.py` (no `--check`) writes a deterministic C4 **Component** diagram.
  With `--check` it exits **1** iff the committed diagram differs from a freshly
  rendered one (after whitespace/newline normalisation).
- `--emit-actual` prints a deterministic, round-trippable `dependencies:` block to
  stdout and exits 0.

## 4. Failure handling

- **Drift (exit 1):** classify the new edge WITH the user. If the dependency is
  *intended*, add it to `dependencies`, regenerate `architecture.mmd`, commit
  both. If it is a *mistake*, the **code** changes, not the manifest — the gate
  did its job. Never silence the gate by editing the manifest reflexively.
- **Stale diagram (exit 1 on `--check`):** regenerate and commit `architecture.mmd`.
- **Error (exit 2):** the manifest is missing/malformed or a root is not
  importable; fix the precondition. The runner leaves no partial artifacts.

## 5. Validation gate (before declaring success)

You are **not done** until this exits 0:

```bash
python scripts/validate_skill.py --skill . --tier structural,behavioral
```

The bundled library also has a full unit suite (run from the skill dir):

```bash
python -m pytest tests --cov=adguard --cov-report=term-missing --cov-fail-under=90
```

## 6. Examples

**Example 1 (clean):** a manifest whose declared edges match the code →
`drift_check.py` exits 0 with "matches the manifest".

**Example 2 (drift, edge case):** code has a `core -> api` back-edge the manifest
omits → `drift_check.py` prints `core -> api` and exits 1, naming the
undocumented dependency rather than silently passing.

## Optional: directional rules via import-linter

Graph-equality catches "an edge appeared that isn't declared." It does not express
"this layering must never invert." If the user wants named directional rules, add
`import-linter` as a *second, separate* gate alongside this one — it complements,
not replaces, the drift check.

## Files

- `scripts/drift_check.py` — the drift gate (also `--emit-actual` for bootstrap).
- `scripts/mermaid_gen.py` — manifest → Mermaid C4, with `--check` freshness mode.
- `scripts/adguard/` — reusable library; `extractor.py` is the only grimp-bound
  module, so a future non-Python extractor is an additive change.
- `references/manifest-schema.md` — full manifest field reference.
