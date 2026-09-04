# 0039 — An eval config is untrusted input: allowlist `callable` target imports

- Status: **Accepted.**
- Date: 2026-09-04
- Related: ADR 0038 (`item_error_policy`; `DisallowedImportError` joins
  `FATAL_RUN_ERRORS` there), ADR 0009 (tech-debt baseline: config-driven
  defaults, no hard-coded secrets), `SECURITY.md`,
  `src/eval_harness/core/_paths.py` (`DATA_ROOT`/`OUTPUT_ROOT` confinement — the
  same trust boundary, drawn on the filesystem instead of the import system).

## Context

`CallableTarget` resolved `params.path` ("module:attribute") with a bare
`importlib.import_module` followed by `getattr`, then called the result with the
dataset item's `inputs`. There was no allowlist anywhere: `plugins.py` gates the
component `type` name, never the callable path.

That made an eval config an executable artefact. A config naming
`subprocess:call`, with a dataset item whose `inputs` is a dict, reaches `Popen`
— which builds its argv by iterating its argument, so the dict's **keys** become
a command line. Verified end to end through the real registry:

```
target = TARGETS.create("callable", {"path": "subprocess:call"})
item   = EvalItem(id="poc", inputs={"/bin/echo": 1, "EXECUTED-FROM-EVAL-CONFIG": 2})
out    = target.run(item)

EXECUTED-FROM-EVAL-CONFIG          # the command ran
harness reported error: None       # the harness reported a clean run
```

The run reports **success**, not an error, because `CallableTarget.run` reports
whatever the callable returned. A second variant needs no attribute at all:
`import_module` executes a module's import-time side effects before `getattr` is
ever reached.

Three things made this live rather than theoretical:

1. `demo/configs/` already ships configs using `type: callable`, and `demo/` is
   **not** in `PROTECTED_PATTERNS` — so a pull request can add a weaponised demo
   config with no `eval-change-approved` label and no CODEOWNER review.
2. No document states that configs are trusted input. `README.md` lists
   `callable (dynamic import)` as a plain feature; `SECURITY.md` scopes
   credential handling and says nothing about config trust.
3. Configs are exactly the artefact people paste from an issue, a shared repo,
   or a colleague.

## Decision

**The control lives in the environment, not the config.** A config-supplied
allowlist would be worthless, because the config is the untrusted side of the
boundary. `EVAL_HARNESS_CALLABLE_TARGET_ALLOWLIST` is read from the process
environment, which the operator running the harness sets and a config author
cannot reach.

**Unset means deny.** This is a deliberate breaking change. The previous
default — "import anything this interpreter can reach" — is not a default a tool
that loads YAML from disk can keep. The refusal names the variable and the
module, so recovery is a single `export`.

**The check precedes the import.** Checking afterwards would be worth nothing:
importing *is* the dangerous act for a module that does work at its top level.
This is asserted by a test that stubs `import_module` and proves it is never
called on the denied path.

**Matching is on dotted-component boundaries, never a raw string prefix.** An
entry of `tests` admits `tests` and `tests._sut`, and refuses `tests_evil`. A
naive `startswith` here would reproduce exactly the bug that made `DATA_ROOT`
containment bypassable through a sibling directory sharing its prefix — the
same mistake, one subsystem over.

**`DisallowedImportError` subclasses `ImportError`.** A denial *is* a refusal to
import, so `except ImportError` keeps working and the matrix's M6 error row
still expresses a true statement.

**A refusal aborts the run.** `DisallowedImportError` joins `StateResetError` in
ADR 0038's `FATAL_RUN_ERRORS`, so it is never converted into a recorded item
failure. Otherwise every item would fail identically and produce a "completed"
run with everything red — precisely the misleading artefact ADR 0038 exists to
prevent. A trust decision is not N independent measurements.

**`*` is supported, and is loud.** An operator who authored every config can
disable the gate, and it logs at WARNING *every time it is honoured*, so it
cannot be set in CI and quietly forgotten.

## Consequences

**Existing `callable` configs break until the operator opts in.** That is the
intended cost of closing an execution path. It is a one-line environment
change, and the error message is the documentation.

**The test suite declares its own allowlist, once.** `tests/conftest.py` sets
`tests,json,nonexistent` rather than editing the eleven test modules that
resolve a callable. It is enumerated rather than `*` on purpose: the gate stays
**live** for the whole suite, so a test reaching for `subprocess` or `os` would
still be refused. Each entry is justified in a comment — notably `nonexistent`,
without which the matrix M6 row would be refused by the allowlist first and pass
for the wrong reason.

**`config/trajectory_eval.yaml`, `demo/`, and the docs need the variable.** They
are operator-controlled contexts; the demo runner and quickstart say so.

**This does not harden every dynamic-dispatch site.** `scorers/__init__.py` does
`getattr(autoevals, scorer)(**scorer_kwargs)` with a config-supplied name. It is
materially weaker — scoped to one module's namespace rather than every importable
module — but it is the same shape and is not addressed here. Tracked as
follow-up rather than folded in, because constraining it well needs the set of
valid `autoevals` evaluator names, which is a different piece of research.

## Alternatives considered

**Deny-list dangerous modules (`subprocess`, `os`, `shutil`).** Rejected:
denylists are bypassable by construction. `builtins`, `importlib`, `ctypes`,
`pty`, and any third-party package with a shell wrapper all reach the same
place, and the list can never be finished.

**Default-allow with opt-in hardening.** Rejected: it leaves the vulnerability
armed for everyone who does not read the release notes, which is everyone.

**A small built-in default allowlist covering the repo's own usage.** Rejected:
it would bake `tests` and `demo` into production code, and it would still admit
whatever a config author named inside those prefixes.

**Resolve the callable eagerly in `__init__` so a bad path fails at engine
construction.** Better operator experience, and rejected for now because it
moves when an unresolvable path is reported and would break the matrix M6 row,
which constructs a target with a missing module and asserts the failure happens
at `run()`. Worth revisiting on its own evidence.
