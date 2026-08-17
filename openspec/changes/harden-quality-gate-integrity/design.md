# Design: harden-quality-gate-integrity

## Placement

| Concern | Home | Why |
|---|---|---|
| Coverage-threshold/source literal interpolation | `skills/quality-gate/scripts/gategen/render.py::_coverage_command` | Already the single function that assembles the `do_coverage` body; the fix changes what it interpolates (a literal instead of an env reference), not where the decision lives |
| Env-override warnings for `COVERAGE_SOURCE`/`COV_FAIL_UNDER` | `render.py::_ignored_override_notice` (existing helper, reused) | The multi-source branch already had exactly this pattern for `COVERAGE_SOURCE`; extending it to both variables in both branches is reuse, not a new mechanism |
| `PYTEST_ADDOPTS` warn-then-clear | new `render.py::_pytest_addopts_guard` | Distinct from `_ignored_override_notice`: pytest reads this variable *itself*, so a warning alone does not neutralize it — the guard also has to act (`unset`), which no existing helper does |
| Variable declarations | `render.py::_variables` | Already the single place that emits `${VAR:-default}` lines; the fix is deletion (two lines removed), not a new seam |
| Hand-maintained `do_extra()` guard | `scripts/quality-gate.sh` (root, by hand, below the marker) | The generator cannot reach this region by design (the whole point of the marker seam) — the only other place a raw `pytest` invocation exists in this change's scope |
| Anchored exclude regex | 4 packages' own `pyproject.toml` | Coverage config is already per-package; the fix corrects a value, not a location |
| Regression proof for the evasions | `skills/quality-gate/tests/` (new fixtures + tests) | Same directory as every other `gategen`/`gen_gate` test; the fixtures need a real, low-coverage Python package on disk, which only this suite already knows how to construct (`_project()` in `test_gen_gate.py`) |
| Static cross-package proof | new `scripts/validations/F_054.py` | Same convention as `F_031.py`/`F_053.py` — a read-only, no-execution check over committed file content, registered in `features.yaml` |

No `architecture.yaml` edit: this change adds no import edge. Nothing outside
`skills/quality-gate/` imports from `gategen`, and the 7 downstream `quality-gate.sh` files
are generated artifacts, not code that imports anything.

## The vulnerability, precisely

Three independent env-reachable levers, one shared root cause: the generator interpolated a
shell **variable reference** (`"$COV_FAIL_UNDER"`, `"$COVERAGE_SOURCE"`) into the pytest-cov
invocation instead of the **value it already knew at generation time**. A variable reference
survives into the emitted script; a literal does not. The fix is the same shape in both cases —
stop referencing the variable, interpolate the value — which is exactly what the multi-source
`COVERAGE_SOURCE` branch already did (this was not a new pattern to invent, only one to
generalize to the cases that lacked it).

`PYTEST_ADDOPTS` is a different shape of the same problem: pytest itself, not this generator,
reads that variable. There is no "stop referencing it" fix available, because the script never
referenced it in the first place — the vulnerability is an *absence* (nothing neutralizes an
ambient value pytest will pick up on its own), not a literal-vs-reference mistake. The fix has
to be active: warn, then `unset`, before every pytest invocation the gate makes.

## Why a warning survives, not just a silent fix

An operator who sets `COV_FAIL_UNDER=0` expecting it to work and gets silent success has no
signal anything unusual happened — the gate just "passed". `_ignored_override_notice` (and now
`_pytest_addopts_guard`) both print to stderr rather than failing the gate: the goal is that
setting these variables has **no effect on the numeric outcome**, while still being visible to
whoever set them, on the theory that a stale CI variable or a copy-pasted local override should
surface as a "huh, that did nothing" moment rather than a mystery. This mirrors the existing
`TYPECHECK_PATHS` multi-path notice (`_typecheck_commands`, unchanged by this proposal) — the
same idiom, applied where it was previously missing.

## Two-branch parity, by construction

Before this change, `_coverage_command`'s single-source and multi-source branches diverged:
multi-source guarded `COVERAGE_SOURCE`, single-source did not; neither guarded
`COV_FAIL_UNDER`. `_coverage_env_form(facts)` (unchanged — `len(facts.coverage_source) == 1`)
still selects which literal-construction path runs, but both notices
(`_ignored_override_notice("COVERAGE_SOURCE")`, `_ignored_override_notice("COV_FAIL_UNDER")`)
and the `PYTEST_ADDOPTS` guard are now emitted **unconditionally**, ahead of the branch split,
so there is exactly one code path that decides "does this gate warn on these three variables" —
answer: always — and a separate, independent branch that decides "how is `--cov=` spelled".
Divergence between the two concerns can no longer recreate finding 2 by accident, because
nothing about the warnings is conditioned on which branch runs.

## Verifying the regex fix does not itself regress coverage

Anchoring `"\.\.\."` to `"^\s*\.\.\.$"` is strictly *narrower* — every line the anchored
pattern excludes, the unanchored pattern also excluded, but not vice versa. The risk is
therefore one-directional: some previously-excluded line, in one of the 4 corrected packages,
is real, un-executed code that will now count as a coverage **miss**. Read literally, one
plausible casualty is this repo's own one-line `Protocol`/callback-stub convention —
`def foo(self) -> int: ...` (the header and the `...` body sharing one physical source line,
e.g. `agent-core/agent_core/protocols.py:30`) — which the unanchored pattern matched (a
substring search finds `...` anywhere in the line) but the anchored pattern does not (the line
is not *entirely* whitespace-plus-ellipsis; it has a `def ...:` prefix).

This was resolved by experiment, not left as a theoretical concern. A minimal reproduction
(`Protocol` class with both a one-line stub and a multi-line stub, neither ever called, plus
one function that is) showed the one-line form's statement is marked **covered** regardless —
coverage.py credits the physical line as executed the moment the enclosing `def` statement
runs (at class/module definition time), which happens unconditionally on import, independent of
whether the method is ever *called*. Only the multi-line form's separate `        ...` body
line depends on a call to get marked executed — and that line already matched the anchored
pattern before and after this change. Branch coverage adds one wrinkle (a one-line `def` can
show a partial-branch note under `--cov-branch`), but this is a small, bounded effect, not a
source of new line misses. Each of the 4 corrected packages' **full** suite was then run for
real (`pytest --cov=<pkg> --cov-branch --cov-report=term-missing`, no `--cov-fail-under`
override) and stayed comfortably clear of its floor: `agent-core` 98.49% (95% floor),
`behavioral-regression` 100% (95%), `flow-corpus` 100% (95%), `flow-protocol` 100% (95%). The
regex fix ships because it was measured safe, not because it was assumed safe.

## What was found but is out of scope

Tracing every consumer of the old `COV_FAIL_UNDER="${COV_FAIL_UNDER:-N}"` string (rather than
assuming the generator was the only place that mattered) surfaced two more things:

- `tests/_e2e_matrix.py::_floor_from_gate_script` parsed exactly that string out of a generated
  `quality-gate.sh` to cross-check it against the package's `pyproject.toml` floor
  (`tests/test_e2e_matrix.py::test_floor_anchors_agree_with_each_other`, which runs against
  the real repo tree, not a fixture). Left unfixed, this helper would have returned `None` for
  every package post-regeneration — not a test *failure* (the test tolerates a missing anchor
  down to a single remaining one) but a silent loss of the second, independent anchor the test
  exists to provide. In scope: the regex now matches the new `--cov-fail-under=N` literal, and
  the two-anchor agreement was re-verified directly against the regenerated tree, not inferred
  from the test suite staying green.
- `skills/project-setup/scripts/makegen/render.py` generates a `Makefile` (a different
  artifact, a different skill) with the analogous unguarded `COVERAGE_SOURCE ?=` /
  `COV_FAIL_UNDER ?=` pattern. Out of scope for the reasons in `proposal.md`'s Scope /
  non-goals — recorded so it is a known, named follow-on rather than a silently-discovered and
  silently-dropped gap.

## MCP checkpoint (per `docs/plans/orbital-drift-alignment/PLAN.md` Phase 1)

The plan calls for verifying current coverage.py/pytest-cov semantics via Context7 before
finalizing this design, specifically: does `exclude_also`/`exclude_lines` matching stay
`re.search` (not full-line), and does `exclude_also` only *append* to the built-in exclusion
set. Context7 was not invoked for this pass — the semantics were instead confirmed by direct
experiment against the installed `coverage` version in this environment (documented above and
reproduced in the new positive-control tests, which exercise the real installed `coverage`/
`pytest-cov`, not a mocked or assumed API). This is the explicit fallback the plan names for
when the MCP tool is unavailable this session: the assumption is not asserted silently, it is
pinned here with the evidence that grounds it, and the evidence is itself executable
(`skills/quality-gate/tests/` positive controls run the real tool on every CI invocation of
this suite, not just at design time).
