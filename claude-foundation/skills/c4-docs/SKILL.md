---
name: c4-docs
description: Generates or updates C4 architecture documentation as Mermaid diagrams in the host repo (docs/architecture/ by default, or the repo's existing docs location). Produces Level 1 context and Level 2 container diagrams, plus Level 3 components only for the subsystem being changed. Updates existing diagrams in place and flags drift between diagrams and code instead of silently rewriting them.
when_to_use: Use when the user asks for architecture documentation, C4 or Mermaid diagrams, a system overview, or when a structural change makes existing architecture docs stale. Not for API reference docs, READMEs, or inline code comments.
---

# C4 Architecture Docs (Mermaid)

Produce C4 diagrams as Mermaid in the repository so they render on GitHub without a
build step.

## Procedure

1. **Locate the docs home.** If architecture docs already exist (search for
   `C4Context`, `C4Container`, or `docs/architecture`), use that location and update
   in place. Otherwise create `docs/architecture/` at the repo root.

2. **Inventory (read-only).** Scan the codebase without modifying it: entry points
   (main functions, servers, CLIs, handlers), top-level modules/packages, external
   dependencies (databases, queues, third-party APIs), and deployment manifests.
   Record what each module does and what talks to what, citing the files you derived
   it from.

3. **Level 1 — System Context.** One diagram: the system as a single box, its users
   (personas), and external systems it depends on. Use Mermaid `C4Context` syntax.

4. **Level 2 — Containers.** One diagram: deployable/runnable units (services, apps,
   databases, queues) and the protocols between them. Use `C4Container` syntax. Every
   container must map to something findable in the repo (a package, service dir, or
   manifest) — no aspirational boxes.

5. **Level 3 — Components (scoped).** Only for the subsystem currently being changed
   or explicitly requested. Do not diagram every container to Level 3; that decays
   fastest and costs most to maintain. Use `C4Component` syntax.

6. **Keep it renderable.** Fence every diagram as ```` ```mermaid ```` and stick to
   Mermaid's C4 syntax (`C4Context`, `C4Container`, `C4Component`, `Person`,
   `System`, `Container`, `Component`, `Rel`, `Boundary`). Avoid experimental
   directives that GitHub's renderer rejects. Keep diagrams under ~20 elements; split
   by boundary if larger.

7. **Update, don't duplicate.** When a diagram for the same level and scope exists,
   edit it. Never create `containers-v2.md` or a parallel diagram alongside a stale
   one.

8. **Flag drift.** Where the existing diagram and the code disagree, do not silently
   rewrite the diagram to match either side. List each discrepancy (diagram says X,
   code at `<file>` shows Y) in your summary, update the diagram to match the code,
   and note that the change reflects observed drift — so reviewers can catch cases
   where the code, not the diagram, is wrong.

## Output

New or updated markdown files containing the Mermaid diagrams, plus a short summary:
files touched, diagrams added vs. updated, and any drift flagged.
