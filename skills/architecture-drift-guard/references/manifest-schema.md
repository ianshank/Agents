# Manifest schema (`architecture.yaml`)

The manifest is the single source of truth. It is loaded, migrated, env-interpolated,
optionally overridden (`--set key.path=value`), then validated.

```yaml
schema_version: "1.0.0"        # required; drives backward-compatible migrations
root_packages:                 # required; top-level importable packages grimp analyses
  - myapp
sys_path:                      # optional; dirs prepended to sys.path so roots import
  - "${REPO_ROOT:-.}/src"
components:                    # required; component name -> owned package prefixes
  payments: [myapp.payments]
  core:     [myapp.core]
dependencies:                 # optional; declared DIRECT component edges (from -> [to])
  payments: [core]            # empty/omitted when bootstrapping
output:                       # optional
  mermaid_path: architecture.mmd
  title: My Service — Component View
```

## Fields

| Field | Required | Meaning |
|-------|----------|---------|
| `schema_version` | yes | Current is `1.0.0`. Older versions are migrated automatically (e.g. `0.9` used `modules:` for `components:`). |
| `root_packages` | yes | Importable package names grimp builds the graph from. Must be non-empty; each must be importable. |
| `sys_path` | no | Directories prepended to `sys.path` before extraction, so `root_packages` resolve without installation. Supports `${VAR}` / `${VAR:-default}`. |
| `components` | yes | Map of component name → list of package prefixes it owns. Modules are assigned to the component with the **longest** matching prefix. |
| `dependencies` | no | Map of `from` component → list of allowed `to` components. These are the declared **direct** edges; anything observed in code but not listed here is drift. |
| `output.mermaid_path` | no | Where `mermaid_gen.py` writes/checks the diagram (default `architecture.mmd`). |
| `output.title` | no | Diagram title (default "Architecture — Component View"). |

## Notes

- **No hardcoded values:** paths and environment-specific values come from
  `sys_path`/`output` and `${VAR:-default}` interpolation, never from code literals.
- **Direct, not transitive:** edges reflect direct imports; transitive folding makes
  everything depend on everything and kills the signal.
- **Self-edges and unknown components** are rejected at validation time.
