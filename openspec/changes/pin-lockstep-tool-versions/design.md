# Design: pin-lockstep-tool-versions

## Placement

| Concern | Home | Why |
|---|---|---|
| `RUFF_VERSION`/`MYPY_VERSION` source of truth | `scripts/tool_versions.py` | Mirrors `scripts/eval_protected_paths.py`'s role for `PROTECTED_PATTERNS`: a plain constants module every consumer is checked against, with no installs or logic of its own |
| Lockstep proof | `scripts/validations/F_054.py` | Same family as `scripts/validations/F_031.py` — CI-governance checks that read committed config/workflow text and run nothing |
| Decision record | `docs/decisions/0034-tool-version-lockstep.md` | New numbered ADR per `docs/decisions/README.md`'s "next free number" convention |

No engine, registry, or `src/eval_harness` code is touched. `architecture.yaml` is
unchanged — this change adds no import edge; `scripts/tool_versions.py` has zero
dependents besides `scripts/validations/F_054.py`, which already sits outside the
architecture-drift-guard's tracked component graph (validators are gates, not
components).

## Parsing approach: regex over raw text, not a TOML/YAML parser

`F_054.py` matches `\b(ruff|mypy)==([^"'\s]+)` against each file's full text. Two
properties of this choice are deliberate, not accidental simplicity:

1. **It is not anchored to a line.** `experiments/backend-validation/pyproject.toml`
   formats its `dev` extra across multiple lines (`"mypy==2.1.0",` / `"ruff==0.15.20",`
   on their own lines, `experiments/backend-validation/pyproject.toml:38-39`); the other
   six `pyproject.toml` files and all 9 `skills-ci.yml` install lines are single-line.
   A pattern anchored to `^...$` per line, or requiring both tokens on one line, would
   need a second code path for the one multi-line file. Because each `tool==version`
   token is intact on a single line regardless of how the surrounding list is
   formatted, one unanchored pattern covers both shapes with no special-casing —
   verified by running it against the real multi-line file, not assumed.
2. **It stays read-only by construction, not merely by omission.** A regex `findall`
   over a string cannot write back to that string. Parsing `skills-ci.yml` into a
   structured YAML/TOML model — even read-only today — would leave a natural next step
   ("now write the corrected value back") sitting one function call away. Staying at
   text-in, text-out keeps the validator structurally incapable of the thing Phase 0 of
   `docs/plans/orbital-drift-alignment/PLAN.md` requires it not do to `skills-ci.yml`.

Two independent checks run per tool (`ruff`, `mypy`) per file:

- **Presence** — at least one `tool==` occurrence exists. Catches a pin silently
  dropped entirely (loosened to `ruff>=`, or deleted) — a different-shaped drift than a
  wrong version, but drift all the same. This is the same "vacuity is refused"
  discipline [ADR 0032](../../../docs/decisions/0032-matrix-completeness-policy.md)
  applies to an empty component census, applied here to an empty pin.
- **Exact match** — every occurrence found equals `tool_versions.py`'s constant,
  checked individually (not via a single aggregated set comparison), so a failure names
  the specific wrong value next to the file it was found in.

Neither check hardcodes "must be exactly N occurrences." `skills-ci.yml` happens to
carry the pin 9 times today; the validator counts whatever is actually there and checks
each one. A 10th skill job added later with the correct pin passes without touching
this file; added with a wrong pin, it fails like every other occurrence would. Hardcoding
"9" would duplicate a fact `scripts/check_skill_script_drift.py`/the `all-skills` CI job
(F-050) already owns, and would drift from *that* the same way this whole change exists
to stop pins drifting — the F-052 "derive, don't restate" principle applied one layer up.

## Known scope boundary: comments are trusted

The regex does not distinguish a live dependency-list pin from a `ruff==X` token that
happened to appear inside a comment. At introduction, none of the 8 covered files
contains such a comment — verified by reading each file's full text before writing the
check, not assumed — including the root `pyproject.toml`'s own drift-history comment
("0.8.0 local vs 0.15.20 CI", `pyproject.toml:82`), which does not use `tool==version`
syntax and so does not match. This mirrors an existing trust assumption in the same
validator family: `F_031.py` regexes `pyproject.toml`'s `[tool.ruff]` section and
`mypy_path` value directly rather than parsing TOML, on the same read-only-config-text
precedent. A future comment reading, say, "previously ruff==0.14.0" would produce a
false failure naming that exact file and value — an easily-diagnosed cost, judged
acceptable against adding a full TOML/YAML parser to a read-only text check in this
family's established shape.

## Logging

Following `AGENTS.md` "Logging": `scripts/validations/F_054.py` obtains
`logger = logging.getLogger(__name__)` and calls `scripts/validations/_common.py`'s
`configure_logging`/`report`/`check`, exactly like every other `F_0NN.py` validator — no
`logging.basicConfig` of its own.

`scripts/tool_versions.py` carries **no logger at all**. Checked against this repo's own
`scripts/*.py` convention (`grep -r getLogger scripts/`, 58 files) before deciding: every
hit is either a CLI entrypoint or a validator with branching to diagnose.
`scripts/eval_protected_paths.py` — the closest existing analog, a plain single-sourced
constant (`PROTECTED_PATTERNS`) consumed by CI guards, with helper functions but no CLI
of its own — carries no logger either. `tool_versions.py` has even less runtime surface
(two string constants, no functions), so the same precedent applies with more force. A
logger with nothing to log would be decoration, not diagnostics.

## What is reused, and what is not

**Reused:** `scripts/validations/_common.py`'s `check`/`report`/`configure_logging` (no
new helper module); the `sys.path` bootstrap idiom every `F_0NN.py` file already carries;
the read-only-text-scan-of-committed-config shape `F_031.py` established for this exact
validator family.

**Not reused:** `_common.ci_enforces`/`delegates_to_gate`. Those exist to assert that a CI
*step* runs somewhere in the ADR-0021 delegation chain (inline in a workflow, or via the
generated `quality-gate.sh`) — a wiring question. F-054 is not asserting a step runs
somewhere; it is asserting a *value* — that `ruff==0.15.20` typed in file A equals
`ruff==0.15.20` typed in file B. Reusing the delegation-aware helpers here would imply a
guarantee this check does not make and does not need.

## Edge cases

| Case | Behaviour |
|---|---|
| A `pyproject.toml` dev extra reformatted onto multiple lines | Handled — the regex is not anchored to a line; `experiments/backend-validation/pyproject.toml` already ships this way today |
| A pin loosened from `==` to `>=` | Caught as a presence failure (zero `tool==` occurrences), not silently passed |
| `skills-ci.yml` gains a 10th skill job with the correct pin | Passes with no `F_054.py` change — occurrences are counted dynamically |
| `skills-ci.yml` gains a 10th skill job with a wrong pin | Caught — every occurrence found is checked individually, regardless of count |
| `tool_versions.py` is bumped without propagating the value everywhere | All still-unpropagated copies fail individually, each naming its own file and the mismatched value found |
| A comment elsewhere in a covered file contains literal `tool==version` text | Would false-fail, naming that file/value (see "Known scope boundary" above) — not exercised today, since no covered file has one |
