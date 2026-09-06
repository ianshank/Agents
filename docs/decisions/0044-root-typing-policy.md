# 0044 — Root-package typing policy: strict under the CI install profile

- Status: **Accepted.**
- Date: 2026-09-06
- Related: `pyproject.toml` `[tool.mypy]`, ADR 0034 (Python 3.11+ floor),
  `docs/roadmap/epic-3-monorepo-and-ci-infrastructure.md`, `NEXT_STEPS.md`
  ("Decide the root package's typing policy").

## Context

`src/eval_harness` was the only package in the monorepo not held to `mypy --strict`;
all five siblings are strict and clean. The root package ships `py.typed`, so
downstream consumers type-check against it — its annotations are a public surface.

Two observations blocked a naive flip:

1. **The errors split into two classes.** Of the 37 `--strict` errors at decision time,
   28 were mechanical (bare `dict`/`Match` generics, missing annotations on our own
   functions). The 9 remainder looked profile-dependent: `type: ignore` comments on
   optional-SDK imports and SDK decorators (`boto3`, `phoenix.evals`, `langfuse.openai`,
   the `observe` seam) whose necessity varies with which extras are installed.
2. **mypy has no per-module `strict` key.** A `strict = true` line inside a
   `[mypy-eval_harness.*]` section applies *globally* (verified against the pinned
   mypy), which would have made `scripts/` and `tests/` strict by accident. Per-module
   overrides are only safe as an enumerated flag bundle.

## Decision

1. **The canonical typing profile is the eval-harness-ci install set**
   (`pip install -e ".[dev,langfuse,openai,parquet]"`). `type: ignore` comments are
   authored to be correct under that profile. A developer with additional SDKs
   installed locally (e.g. `bedrock`, `phoenix-evals`) may see different
   `import-untyped`/`unused-ignore` results; that skew is accepted and documented
   here rather than chased per-profile. (`ignore_missing_imports = true` already
   covers the SDK-absent direction.)
2. **`eval_harness.*` is strict** via a `[[tool.mypy.overrides]]` section that
   enumerates the strict flag bundle individually (never the `strict` key, which
   leaks globally). `scripts/` and `tests/` stay at the repo's existing non-strict
   floor; raising them is separate follow-up work. Two flags from the `--strict`
   bundle are deliberately absent: `warn_redundant_casts` (mypy rejects it in
   per-module sections) and `implicit_reexport = false` (the public-surface guard
   F-039 already pins every module's `__all__` explicitly; flipping it would force
   export-list churn in protected modules — and break `scripts/`/`tests/` imports
   of deliberately internal names like `targets.testgen._suite_runner` — for no
   gate-visible gain).
3. **SDK-seam code is typed at the seam, not at every call site.** The
   `langfuse_client.observe` wrapper carries `overload`s so a decorated function
   stays typed under `disallow_untyped_decorators`; an `Any`-returning decorator
   would silently untype every function it touches.
4. **Unused ignores are deleted, not kept "just in case".** An ignore that is unused
   under the canonical profile is removed in the same PR that enables
   `warn_unused_ignores`; a needed ignore carries a specific error code (never bare).

## Consequences

- `mypy --strict src/eval_harness` is clean and stays that way: the quality gate's
  `mypy src/eval_harness` run enforces the override on every PR.
- The 37-error backlog is resolved: 28 mechanical annotations, 5 unused-ignore
  removals, 2 SDK-decorator/seam typings (`observe` overloads, the `migration`
  decorator factory), 1 ignore recoded to the error the line actually raises
  (`langfuse.openai` → `attr-defined`), 1 bare-dict return in `migrations`.
- Future optional-SDK seams follow the same pattern: lazy import behind
  `ignore_missing_imports`, specific-code ignores only where the canonical profile
  raises, seam wrappers typed with `overload`s.

## Alternatives considered

- **Global `strict = true`:** rejected — `scripts/` (85%-floor operational tooling)
  and `tests/` are not strict-clean, and a big-bang flip would stall feature work
  behind unrelated typing debt.
- **Per-module `strict = true` in an override:** rejected — verified to apply
  globally under the pinned mypy, which is the global flip in disguise.
- **Keep the ignores with `warn_unused_ignores` off for seam modules:** rejected —
  an unused ignore is a stale claim about the type system; the canonical-profile
  rule makes the correct set deterministic.
