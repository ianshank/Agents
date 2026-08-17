# Review: pin-lockstep-tool-versions

**Reviewed:** independently, from scratch, against the tree pinned at `c5d32e5` on
`worktree-agent-a1935d45e12a8002a` — not against the implementer's self-report, which was
not read. Two passes, dated separately: a mechanical fact-check of every falsifiable claim
(verdicts CONFIRMED / CORRECTED / REFUTED, with file:line evidence) and an adversarial
design review with attacks verified before being kept — refuted attacks are recorded, not
deleted. House precedent: `openspec/changes/add-panel-judge/review.md`.

## Verdict

**APPROVE WITH FOLLOW-UPS.** The core deliverable is real and correct: `scripts/tool_versions.py`
and `scripts/validations/F_054.py` exist, match every claim made about them, run clean, and
are genuinely read-only under adversarial inspection (no `eval`/`exec`/`subprocess`/write path
anywhere in the import chain — verified, not assumed). All 7 `pyproject.toml` files and
`.github/workflows/skills-ci.yml` already carry `ruff==0.15.20`/`mypy==2.1.0` in lockstep with
`scripts/tool_versions.py`, ADR 0034 is a genuinely free number, and the two-commit ledger
pattern is sound by construction (git parent immutability rules out the "done with an
unresolvable SHA" window the task asked me to probe for). Two things need attention, neither
of which is a defect in the reviewed code:

1. **Verify-at-merge-time (not a code defect):** this branch's true git parent is `159460a`,
   not `7cdba73` as this review's own task framing assumed — `7cdba73` (which added
   `docs/plans/orbital-drift-alignment/PLAN.md`) is **not an ancestor of `HEAD`**. A raw
   `git diff 7cdba73 HEAD` therefore shows a spurious 251-line deletion of that plan document
   that none of this branch's three commits actually performed. A normal 3-way `git merge` /
   PR merge into a target that already has `7cdba73` resolves this safely (nothing here
   conflicts with or deletes that file); a patch/diff-apply or an unaware rebase would not.
   See Pass 1, finding P1-F1.
2. **Scope gap, pre-existing, not introduced by this change:** `agent-core/.pre-commit-config.yaml`
   pins `ruff-pre-commit` at `rev: v0.8.0` — a live, contributor-facing, currently-drifted
   ruff pin (the fleet is `0.15.20`) that F-054 does not check and ADR 0034's "eight files,
   sixteen copies" census does not mention. See Pass 2, finding P2-F1.

Both are recorded as follow-ups below, not blockers — see "Overall verdict" at the end for the
precise reasoning and required actions.

---

## Pass 1 — Mechanical fact-check (2026-08-17, tree pinned at `c5d32e5`)

| # | Claim | Verdict | Evidence |
|---|---|---|---|
| P1-1 | `scripts/tool_versions.py` exists, defines `RUFF_VERSION="0.15.20"`, `MYPY_VERSION="2.1.0"` | **CONFIRMED** | `scripts/tool_versions.py:27-28`, read directly |
| P1-2 | Those constants match root `pyproject.toml` | **CONFIRMED** | `pyproject.toml:84` — `"mypy==2.1.0", "ruff==0.15.20"` |
| P1-3 | All 7 named `pyproject.toml` files carry the identical pins | **CONFIRMED** | `agent-core/pyproject.toml:34`, `behavioral-regression/pyproject.toml:36`, `claude-foundation/pyproject.toml:36`, `experiments/backend-validation/pyproject.toml:38-39`, `flow-corpus/pyproject.toml:35`, `flow-protocol/pyproject.toml:35` — all `ruff==0.15.20`/`mypy==2.1.0`, checked by direct `grep`, not trusted from the module docstring |
| P1-4 | The other 5 `pyproject.toml` files in the repo (fixtures under `skills/*/evals/fixtures/`) are correctly out of scope | **CONFIRMED** | None of the 5 pin a version (`ruff`/`mypy` unpinned or absent) — they are eval-harness test fixtures, not real dependency manifests |
| P1-5 | `F_054.py` reads all 7 `pyproject.toml` files plus `.github/workflows/skills-ci.yml` | **CONFIRMED** | `scripts/validations/F_054.py:52-60` (`_PYPROJECT_PATHS` tuple, 7 entries) and `:64` (`_SKILLS_CI_WORKFLOW`); `main()` at `:113-116` iterates both |
| P1-6 | `F_054.py` actually runs and passes | **CONFIRMED** | Ran `python3 scripts/validations/F_054.py` directly — exit 0, full output pasted below |
| P1-7 | **"Zero diff on all 7 `pyproject.toml` files and `skills-ci.yml`"** (the task's single most important claim) | **CONFIRMED for the specific files**, but see P1-F1 below | `git diff 7cdba73 HEAD --stat` lists 13 changed files; none of the 7 `pyproject.toml` files or `skills-ci.yml` appear in it at all — zero touches, not "diff exists but is empty." The read-only validator did not become a write. |
| P1-8 | ADR took a genuinely free number, 0034 | **CONFIRMED, with a stated limitation** | `docs/decisions/` has 0001-0033 pre-existing, 0034 newly added by this change (`git log --all --oneline -- docs/decisions/0034*` → one commit, `86eeb5c`, from this branch only). Checked all 4 sibling worktrees on disk (`agent-a0d0b0246d3e791ad`, `agent-a677e84000123bf93`, `agent-a83ed32a5c4dec0db`, and `/home/user/Agents` itself) — none claim 0034. **Limitation:** this is a shallow-ish clone with only `origin/main` and `origin/claude/orbital-drift-agents-reuse-aely36` fetched (confirmed via `git branch -a`), so a same-numbered ADR proposed on some other, unfetched remote branch cannot be fully ruled out — noted, not swept under the rug. |
| P1-9 | `AGENTS.md`'s pin bullet now points at `scripts/tool_versions.py` | **CONFIRMED** | `git diff 7cdba73 HEAD -- AGENTS.md` — one line changed, `AGENTS.md:97`, matches `docs/plans/orbital-drift-alignment/PLAN.md` Phase 2's exact instruction |
| P1-10 | ADR 0034's citations are accurate to the line | **CONFIRMED** | Spot-checked all three: `pyproject.toml:81-83` (the "0.8.0 local vs 0.15.20 CI" comment), `agent-core/pyproject.toml:31-33`, `claude-foundation/pyproject.toml:34-35` — every one matches the live file byte-for-byte at the cited lines |
| P1-11 | `proposal.md`'s "six of the seven `pyproject.toml` copies carry the exact 'bump deliberately, in lockstep' phrase" | **CONFIRMED** | Checked all 7 directly; `experiments/backend-validation/pyproject.toml` is the one exception (it says "Same exact pins as the repo root" instead) — exactly as claimed, including which file is the exception |
| P1-12 | `F_054.py` follows `F_031.py`'s shape (same `_common` helpers, same read-only/deterministic/offline design) | **CONFIRMED** | Both import `_common.check`/`report`/`configure_logging`; both carry the same `sys.path` bootstrap idiom; `F_031.py`'s own docstring makes the identical "reads config/workflow files only, runs nothing" claim |
| P1-13 | The two-commit ledger pattern matches the F-053 precedent it cites | **CONFIRMED** | `git show bc0ae2c4940f0ecdfa50da47f1c249cb16b77e02` and `git show f1f73a3` both exist and show the identical `in_progress` → `done` + `implemented_in`-set-in-the-child-commit shape |
| P1-14 | `features.yaml` is schema-valid | **CONFIRMED** | Independently validated with `python3 -c "import jsonschema; ..."` against `features.schema.json` (not just trusting the repo's own validator) — passes |
| P1-15 | F-054 is genuinely the next free F-ID, no collision | **CONFIRMED** | F-053 is the highest ID at the true merge-base (`159460a`); F-054 appears exactly once in `features.yaml` at HEAD |
| P1-16 | `ruff`/`mypy` at the exact pinned versions run clean against the two new files | **CONFIRMED** | This environment has `ruff 0.15.20` / `mypy 2.1.0` installed (matching the pin exactly, by chance of environment, not engineered for this review); `ruff check`, `ruff format --check`, and `mypy` all pass clean on `scripts/tool_versions.py` and `scripts/validations/F_054.py` |
| P1-17 | `proposal.md`'s "this implementation carries the `eval-change-approved` label" | **UNVERIFIABLE from the tree** | This branch has no upstream tracking ref (`git branch -vv` shows none) and has never been pushed — there is no PR yet to carry a label. Not a defect; the sentence reads as present tense but is necessarily a forward statement today. |
| P1-18 | Phase 0 §5's worktree-naming convention (`worktree-<change-id>`) was followed | **CORRECTED (informational)** | The branch is `worktree-agent-a1935d45e12a8002a`, not `worktree-pin-lockstep-tool-versions`. This is almost certainly the CCR session/worktree provisioning system's own naming, not a choice available to the implementer — noted, not weighted against the change. |
| P1-19 | Phase 0's cross-cutting "Objective peer-review step" requires a `tasks.md` "Verification" checklist item for the `review.md` dispatch, in every phase | **CORRECTED — gap found** | `docs/plans/orbital-drift-alignment/PLAN.md`'s "Objective peer-review step" section (its "Enforcement" bullet) requires this for every phase. `openspec/changes/pin-lockstep-tool-versions/tasks.md`'s "## 6. Verification" section has 3 items; none reference `review.md` or the peer-review dispatch. Real, confirmable gap against the plan's own requirement — paperwork, not function (this document is the review the plan asked for; it just wasn't tracked as a checklist line). |

### P1-F1 — The branch's actual base is not `7cdba73` (full detail)

This is the most consequential thing this review found, so it gets its own section rather
than one table row.

`git merge-base --is-ancestor 7cdba73 HEAD` → **NO**. `git merge-base 7cdba73 HEAD` →
`159460af64f35ee6290f67e5d211c9658ee88416`, which is `7cdba73`'s own parent. In other words:
this worktree's three commits (`86eeb5c`, `06dc980`, `c5d32e5`) branch from **`159460a`**, one
commit *before* `7cdba73` — not from `7cdba73` itself, despite that being this review's stated
base and despite `7cdba73`'s commit message ("docs: add Orbital-Drift alignment implementation
plan") being the very document this change's own commit messages, ADR, and `features.yaml`
notes all cite by path (`docs/plans/orbital-drift-alignment/PLAN.md`).

Consequence: `docs/plans/orbital-drift-alignment/PLAN.md` does not exist anywhere in this
branch's history, because the branch forked before it was added. `git diff 7cdba73 HEAD --stat`
renders this as a 251-line full deletion of that file — which is **not** something any commit
in this branch performed (verified individually: `git show --stat` on `86eeb5c`, `06dc980`, and
`c5d32e5` shows none of them touch that path), but an artifact of diffing across two branches
that share an ancestor two commits back rather than a linear parent chain. Confirmed the
blast radius is exactly one file: `git diff 159460a 7cdba73 --stat` shows `7cdba73`'s entire
own diff from its true parent is the 251-line PLAN.md addition and nothing else, so no other
entry in the 13-file `git diff 7cdba73 HEAD --stat` output is contaminated by this gap — the
"zero diff on the 7 `pyproject.toml` files + `skills-ci.yml`" claim (P1-7) is unaffected and
remains cleanly CONFIRMED.

**Practical risk is low, not zero, and depends entirely on how this branch gets integrated.**
A real 3-way `git merge` (or a GitHub PR merge, which is a 3-way merge) into any target that
already contains `7cdba73` computes: base = `159460a` (no PLAN.md), ours = target (PLAN.md
added), theirs = this branch (PLAN.md untouched/absent) → git adds the file with no conflict,
because only one side ever touched it. That is exactly how `docs/plans/orbital-drift-alignment/PLAN.md`'s
own "Reconvergence" section (`docs/plans/orbital-drift-alignment/PLAN.md`, "each phase's
branch merges independently into this session's designated working branch") says integration
is supposed to happen. The hazard is specifically: applying `git diff 7cdba73 HEAD` as a patch,
or any tooling that treats `7cdba73` as this branch's literal parent for a rebase/cherry-pick
without accounting for the missing commit, **would** delete the plan document for real. Sibling
worktrees `agent-a0d0b0246d3e791ad` and `agent-a677e84000123bf93` do correctly contain `7cdba73`
in their history, confirming this gap is specific to how this one worktree was provisioned, not
a repo-wide problem.

**Required action before/at merge:** whoever integrates this branch should either (a) rebase it
onto `7cdba73` (or the current tip of `claude/orbital-drift-agents-reuse-aely36`) first, or (b)
confirm the integration path is a genuine merge (not a diff/patch replay) into a target that
already has `7cdba73`, and specifically confirm `docs/plans/orbital-drift-alignment/PLAN.md`
is present post-merge. This is not a defect in the reviewed code and does not block approval of
the code itself — see "Overall verdict."

### Pasted output — `python3 scripts/validations/F_054.py`

```
INFO     validations: OK: pyproject.toml: at least one ruff== pin is present
INFO     validations: OK: pyproject.toml: ruff==0.15.20 matches tool_versions.RUFF_VERSION (0.15.20)
INFO     validations: OK: pyproject.toml: at least one mypy== pin is present
INFO     validations: OK: pyproject.toml: mypy==2.1.0 matches tool_versions.MYPY_VERSION (2.1.0)
INFO     validations: OK: agent-core/pyproject.toml: at least one ruff== pin is present
INFO     validations: OK: agent-core/pyproject.toml: ruff==0.15.20 matches tool_versions.RUFF_VERSION (0.15.20)
INFO     validations: OK: agent-core/pyproject.toml: at least one mypy== pin is present
INFO     validations: OK: agent-core/pyproject.toml: mypy==2.1.0 matches tool_versions.MYPY_VERSION (2.1.0)
INFO     validations: OK: behavioral-regression/pyproject.toml: at least one ruff== pin is present
INFO     validations: OK: behavioral-regression/pyproject.toml: ruff==0.15.20 matches tool_versions.RUFF_VERSION (0.15.20)
INFO     validations: OK: behavioral-regression/pyproject.toml: at least one mypy== pin is present
INFO     validations: OK: behavioral-regression/pyproject.toml: mypy==2.1.0 matches tool_versions.MYPY_VERSION (2.1.0)
INFO     validations: OK: flow-protocol/pyproject.toml: at least one ruff== pin is present
INFO     validations: OK: flow-protocol/pyproject.toml: ruff==0.15.20 matches tool_versions.RUFF_VERSION (0.15.20)
INFO     validations: OK: flow-protocol/pyproject.toml: at least one mypy== pin is present
INFO     validations: OK: flow-protocol/pyproject.toml: mypy==2.1.0 matches tool_versions.MYPY_VERSION (2.1.0)
INFO     validations: OK: flow-corpus/pyproject.toml: at least one ruff== pin is present
INFO     validations: OK: flow-corpus/pyproject.toml: ruff==0.15.20 matches tool_versions.RUFF_VERSION (0.15.20)
INFO     validations: OK: flow-corpus/pyproject.toml: at least one mypy== pin is present
INFO     validations: OK: flow-corpus/pyproject.toml: mypy==2.1.0 matches tool_versions.MYPY_VERSION (2.1.0)
INFO     validations: OK: claude-foundation/pyproject.toml: at least one ruff== pin is present
INFO     validations: OK: claude-foundation/pyproject.toml: ruff==0.15.20 matches tool_versions.RUFF_VERSION (0.15.20)
INFO     validations: OK: claude-foundation/pyproject.toml: at least one mypy== pin is present
INFO     validations: OK: claude-foundation/pyproject.toml: mypy==2.1.0 matches tool_versions.MYPY_VERSION (2.1.0)
INFO     validations: OK: experiments/backend-validation/pyproject.toml: at least one ruff== pin is present
INFO     validations: OK: experiments/backend-validation/pyproject.toml: ruff==0.15.20 matches tool_versions.RUFF_VERSION (0.15.20)
INFO     validations: OK: experiments/backend-validation/pyproject.toml: at least one mypy== pin is present
INFO     validations: OK: experiments/backend-validation/pyproject.toml: mypy==2.1.0 matches tool_versions.MYPY_VERSION (2.1.0)
INFO     validations: OK: .github/workflows/skills-ci.yml: at least one ruff== pin is present
INFO     validations: OK: .github/workflows/skills-ci.yml: ruff==0.15.20 matches tool_versions.RUFF_VERSION (0.15.20)
INFO     validations: OK: .github/workflows/skills-ci.yml: ruff==0.15.20 matches tool_versions.RUFF_VERSION (0.15.20)
  [... 6 more identical ruff==0.15.20 OK lines, one per skills-ci.yml job, 8 total ...]
INFO     validations: OK: .github/workflows/skills-ci.yml: at least one mypy== pin is present
INFO     validations: OK: .github/workflows/skills-ci.yml: mypy==2.1.0 matches tool_versions.MYPY_VERSION (2.1.0)
  [... 7 more identical mypy==2.1.0 OK lines, one per skills-ci.yml job, 8 total ...]
INFO     __main__: F-054 passed
```

Exit code: `0`. `git status --short` and `git diff HEAD --stat` both empty before and after
this run — the validator wrote nothing.

### Pasted output — `python scripts/validate.py --tier fast --strict`

```
INFO     __main__: Loading features from features.yaml
WARNING  __main__: shallow clone detected - downgrading --strict provenance checks to warnings; run `git fetch --unshallow` to check them for real
WARNING  __main__: Git: F-001 implemented_in ref '57f7cc2cbcaa3cf618c0b9ec6c5048da11da6796' does not resolve
  [... ~30 more pre-existing "ref does not resolve" warnings for F-002 through F-040, all
       downgraded from hard failures by the shallow-clone warning above — none reference
       F-054, and none were introduced by this change; this is the ambient state of the
       clone this review is running in, not a regression ...]
INFO     __main__: Running validation for F-001: python scripts/validations/F_001.py
INFO     __main__: Validation: F-001 passed ✓
  [... F-002 through F-053, all "passed ✓" ...]
INFO     __main__: Running validation for F-054: python scripts/validations/F_054.py
INFO     __main__: Validation: F-054 passed ✓
OK: 52 done; ran 52 for tier(s) ['fast'], skipped 0 (other tiers).
```

Exit code: `0`. All 52 `done`-status fast-tier features pass, including F-054. The
`implemented_in` ref-resolution warnings for F-001–F-040 are a pre-existing, ambient
consequence of this clone being shallow (`git fetch --unshallow` would check them for real
per the tool's own warning) — none of them concern F-054, and F-054 itself produced **no**
such warning, meaning its own `implemented_in` SHA (`86eeb5cf1db0f17f06e5ed50b90e8c02fc4e939f`)
resolved cleanly.

---

## Pass 2 — Adversarial (2026-08-17, second sitting, same pinned `c5d32e5`)

Assume the design is wrong; try to prove it. All four attacks below were actually executed
against the tree, not reasoned about abstractly. Every mutation made during testing was
reverted and confirmed clean (`git status --short` empty) before moving to the next attack.

### (a) Can the lockstep check be defeated by "fixing" `tool_versions.py` to match the wrong file, instead of fixing the drift?

**Tested two shapes of this attack:**

1. **Lazy/partial "fix":** drifted `agent-core/pyproject.toml`'s `ruff==0.15.20` to
   `ruff==0.14.0` (simulating an accidental bad edit), confirmed `F_054.py` fails naming
   exactly that file and value. Then edited `scripts/tool_versions.py`'s `RUFF_VERSION` to
   also say `"0.14.0"` — i.e., "fixed" the source of truth to match the one wrong copy instead
   of reverting it. **Result: still fails** — now with 8 new errors, because the other 6
   `pyproject.toml` files and every `skills-ci.yml` line still say `0.15.20` and now disagree
   with the changed `tool_versions.py`. A lazy, single-file "fix" cannot produce a passing
   state; it only moves which files are reported as wrong.
2. **Full, consistent propagation:** changed `0.15.20` → `0.99.99` (a version that does not
   exist) in all 7 `pyproject.toml` files, `skills-ci.yml`, **and** `tool_versions.py`
   together. **Result: passes cleanly**, exit 0.

**Verdict: CONFIRMED as a real but *accepted, explicitly documented* limitation, not an
undisclosed bug.** `F_054.py` is a coherence/consistency check ("do all N copies agree with
each other"), not a correctness check ("is this a value that should exist"); it has no
external oracle (no PyPI lookup, no network access — the module docstring is explicit:
"Deterministic and offline: reads files only, runs nothing"). This is exactly what
`docs/decisions/0034-tool-version-lockstep.md`'s Decision §3 and Consequences ("Negative")
sections say in so many words: *"This gate tests drift... not the act of bumping itself"* and
*"The gate proves the copies agree; it does not reduce how many places a correct bump must
touch."* A fully-propagated typo is indistinguishable from a fully-propagated legitimate bump
by construction — that is inherent to any N-way-consistency check, not a design flaw specific
to this one. What the check *does* correctly prevent — a partial, lazy, or accidental edit to
any subset of the 16 copies, including "fixing" the wrong side — was empirically confirmed
above to still fail loudly.

### (b) Does the read-only claim hold under adversarial reading — any `eval`/`exec`/subprocess/write path?

Grepped the entire import chain — `scripts/validations/F_054.py`, `scripts/validations/_common.py`,
`scripts/tool_versions.py`, and `scripts/_cli.py` (transitively imported via `_common`) — for
`eval(`, `exec(`, `subprocess`, `os.system`, `os.popen`, `open(...` in write mode, `__import__`,
`compile(`. **Zero hits** beyond the docstring's own textual claim and one `re.compile(...)`
false-positive (a regex compile, not code compile). `_common.py`'s `check`/`report` functions
only append to an in-memory list and log; `configure_logging` only calls `logging.basicConfig`.
The only file I/O anywhere in the chain is `open(path, encoding="utf-8")` in `_read()`
(`scripts/validations/F_054.py:77-79`), opened in default (read) mode.

Empirically confirmed three separate times during the (a) testing above — including while the
tree was deliberately left in a **failing** state, not just the happy path — that `.github/workflows/skills-ci.yml`'s
mtime and content were unchanged after each run (`stat -c %Y` before/after identical;
`git status --short` clean).

**Verdict: REFUTED.** Attack attempted, no write or execute path found anywhere in the chain,
in either the passing or the failing branch. Recorded per house style despite disproof.

### (c) Is the two-commit ledger pattern actually correct, or is there a window where `features.yaml` claims `done` with an unresolvable SHA?

Read both commits directly. `86eeb5c` (`git show 86eeb5c -- features.yaml`) lands the F-054
row with `status: "in_progress"` and **no** `implemented_in` key at all. `06dc980` (`git show
06dc980 -- features.yaml`), whose sole parent is `86eeb5c`, changes only two things: `status`
`in_progress` → `done`, and adds `implemented_in: "86eeb5cf1db0f17f06e5ed50b90e8c02fc4e939f"`.
Confirmed that string is `86eeb5c`'s exact full SHA via `git rev-parse 86eeb5c`.

**Verdict: REFUTED — no such window exists, by git's own construction, not merely by luck.**
A child commit's parent link is content-addressed and immutable; `06dc980` cannot exist as an
object unless `86eeb5c` already exists as one, in the same object store, reachable from the
same history. There is no point at which a fetcher, CI runner, or `validate.py --strict`
invocation can observe the tree state where `status: done` + `implemented_in: 86eeb5c` is
present without `86eeb5c` itself being present and resolvable — the two facts are committed
atomically together in `06dc980`, referencing an already-existing prior commit. This is not a
novel pattern invented for this change either: cross-checked against the F-053 precedent the
commit messages cite (`git show bc0ae2c4940f0ecdfa50da47f1c249cb16b77e02` — the F-053
ledger-entry-plus-proof commit — and `git show f1f73a3` — the flip-to-done commit setting
`implemented_in: bc0ae2c...`) and found the identical shape, already established house
convention. Recorded per house style despite disproof.

### (d) Are there other repo-wide `ruff==`/`mypy==` pins this change's scope claims to cover but actually misses?

Grepped the full repository (`.toml`, `.yml`/`.yaml`, `.cfg`, `.ini`, `.sh`, `Makefile`, `.txt`)
for `ruff==`/`mypy==`, and separately searched for `.pre-commit-config.yaml` anywhere in the
tree.

**Verdict: CONFIRMED — a real gap, P2-F1 below.** Also found two lower-severity items:

- `.github/workflows/flow-corpus-ci.yml:64` and `.github/workflows/behavioral-regression-ci.yml:47`
  contain **comments** citing `ruff==0.15.20, mypy==2.1.0` for human context ("the install now
  uses [package]'s own pinned `[dev]` extra... instead of a separate unpinned `pip install ruff
  mypy`"). Verified these are genuinely comments, not a second live pin: the actual `install:`
  lines delegate to `pip install -e ".[dev]"` via the `run-quality-gate` composite action,
  reading whatever `pyproject.toml`'s `dev` extra says — already covered by F_054.py. These two
  comments carry no independent drift risk (nothing installs from them), but would go
  *textually* stale after a future version bump with nothing to catch it. Severity: low/cosmetic.
- `.github/workflows/claude-foundation-ci.yml` and `.github/workflows/eval-harness-ci.yml`
  invoke `ruff`/`mypy` with no separate version literal at all (they run whatever was already
  installed from the package's `pyproject.toml` dev extra or the shared quality-gate). No gap.

#### P2-F1 — `agent-core/.pre-commit-config.yaml` pins ruff at `v0.8.0`, live, contributor-facing, and currently drifted

`agent-core/.pre-commit-config.yaml:6-7`:

```yaml
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.8.0
```

This is a real, separate ruff-version pin — via the `ruff-pre-commit` hook's `rev:` field, a
different syntax than the `tool==version` string `F_054.py`'s regex matches, so it would not be
caught even if this file were added to the scan unmodified. It is **not** dormant: `agent-core/CONTRIBUTING.md:33-34`
explicitly documents and instructs contributors to run
`pre-commit run --all-files --config agent-core/.pre-commit-config.yaml`. `agent-core`'s CI
(`agent-core-ci.yml`) does not run this file, so it cannot silently break a merge — but any
contributor following `CONTRIBUTING.md`'s own documented local workflow lints/formats with
ruff `0.8.0` while everything else in the fleet, including this same package's own CI, uses
`0.15.20`.

Notably, **`v0.8.0` is not an arbitrary old version** — it is the exact number `AGENTS.md`,
`scripts/tool_versions.py:6`, and `docs/decisions/0034-tool-version-lockstep.md:19` all cite as
the historical incident that motivated pinning in the first place: *"an unpinned ruff drifted
once already (0.8.0 local vs 0.15.20 CI) and broke `ruff format --check`."* This file was last
touched on 2026-07-03 (`git log --oneline -- agent-core/.pre-commit-config.yaml` → one commit,
`3cca8ae`), over six weeks before this change, and is a strong candidate for literally being
the fossil of that original incident — never updated when the rest of the fleet was pinned to
`0.15.20`, and still not updated by this change.

`mypy` is not separately at risk here: the `mypy-agent-core` hook in the same file is
`repo: local`, running `python -m mypy agent_core` against whatever `mypy` is already installed
in the active environment (presumably from the `dev` extra), not a second independently pinned
copy.

This is not a regression introduced by this change — the drift predates it by six weeks and
this change did not touch the file. But `docs/decisions/0034-tool-version-lockstep.md`'s own
Context section frames "eight files... sixteen hand-typed copies in total" as if it were an
exhaustive census of every ruff/mypy version pin in the repository; this shows that framing is
one copy short of exhaustive, in a copy that is not merely stale documentation but an actually
different, actually reachable tool version. Severity: **MEDIUM** — no CI impact, but it is the
literal problem this whole change exists to solve, still live, in a place a contributor can
actually hit it.

### Attacks that died under verification (kept per house style)

**"A partial edit to just the source-of-truth file could sneak a wrong pin past the gate."**
Refuted by direct test (attack (a), shape 1 above): changing only `tool_versions.py` to match
one drifted file produces *more* failures, not fewer, because the other fifteen copies now
disagree with the changed constant. The gate cannot be defeated by editing only one side.

**"The validator might shell out or write somewhere non-obvious."** Refuted by direct
inspection of the full import chain plus empirical mtime/git-status checks across multiple runs
in both passing and failing states (attack (b) above). No such path exists.

**"The two-commit ledger leaves a window where `done` + `implemented_in` points at a SHA that
doesn't exist yet."** Refuted (attack (c) above) — ruled out by git's own parent-immutability
guarantee, not merely by absence of a failed test.

---

## Findings requiring follow-up

| # | Severity | Finding | Recommended action |
|---|---|---|---|
| P1-F1 | **High (procedural, not code)** | This branch's true parent is `159460a`, not the claimed `7cdba73` — `docs/plans/orbital-drift-alignment/PLAN.md` is absent from this branch's history and shows as a spurious full deletion under a raw `git diff 7cdba73 HEAD` | Rebase onto `7cdba73`/current `claude/orbital-drift-agents-reuse-aely36` tip before merge, **or** confirm the actual integration is a real 3-way merge into a target that already has `7cdba73`, and verify `PLAN.md` is present post-merge. Required at merge time, not deferrable. |
| P2-F1 | **Medium** | `agent-core/.pre-commit-config.yaml:7` pins `ruff-pre-commit rev: v0.8.0`, live and contributor-facing, drifted against the fleet's `0.15.20`, uncovered by F-054, unmentioned in ADR 0034's "eight files" census | Bump the `rev:` to match `v0.15.20` as a fast-follow; consider whether `F_054.py` (or a new, small companion check) should cover pre-commit `rev:` pins in a future change, and correct ADR 0034's Context section to acknowledge this as a known, separately-tracked surface rather than implying the 16-copy census is exhaustive |
| P1-19 | **Low** | `tasks.md`'s "Verification" section omits the `review.md`/peer-review-dispatch checklist item that `docs/plans/orbital-drift-alignment/PLAN.md`'s Phase 0 "Objective peer-review step" requires for every phase | Add the checklist item to `tasks.md` (retroactively checked, since this document now exists) |
| P2 (comments) | **Low / cosmetic** | `flow-corpus-ci.yml:64` and `behavioral-regression-ci.yml:47` cite the version numbers in comments; nothing re-checks them against `tool_versions.py`, so they can go textually stale after a future bump | No action required now; optional: mention in a future bump's checklist to grep for these two comments |
| P1-17 | **Informational** | `proposal.md` states this change "carries the `eval-change-approved` label" in present tense; unverifiable since the branch has no PR yet | No action; will resolve itself once a PR exists |
| P1-18 | **Informational** | Worktree branch name doesn't match Phase 0 §5's `worktree-<change-id>` convention | Almost certainly infrastructure-assigned, not implementer choice; no action |

## Residual risk

- **The census in ADR 0034's Context section is not provably exhaustive.** P2-F1 shows it
  missed one real pin. A repo-wide `grep -rn "rev: v[0-9]"` sweep across all `.pre-commit-config.yaml`
  files (there may be more than the one found under `agent-core/`) would be the honest way to
  close this out completely, and is outside this change's already-landed scope.
- **The lockstep check is coherence-only, permanently.** As long as `F_054.py` stays offline and
  deterministic (a design choice this review agrees with — see attack (a)'s verdict), a fully
  and consistently propagated wrong version will always pass. This is accepted, not a residual
  bug, but worth stating plainly for whoever next touches this file.
- **Shallow clone limited this review's ability to rule out an ADR-0034 collision on unfetched
  remote branches** (P1-8). Low practical likelihood given the local checks all agree, but not
  literally exhaustive.

## Overall verdict

**APPROVE WITH FOLLOW-UPS.**

Every claim about the actual deliverable — `scripts/tool_versions.py`'s constants,
`scripts/validations/F_054.py`'s coverage/behavior/read-only guarantee, the ADR's numbering and
citations, the two-commit ledger's correctness, the OpenSpec package's internal consistency,
and the doc/index updates — was independently re-derived from the tree and **holds**. Both
scripts run clean; `ruff`/`mypy` at the pinned versions pass on the new files; `features.yaml`
is schema-valid; `python scripts/validate.py --tier fast --strict` is green at 52/52 including
F-054. All three adversarial attacks that could have found a defect in the *design* (partial-edit
evasion, hidden write/exec path, ledger race window) were tried and refuted. The one adversarial
attack that landed (P2-F1, the pre-commit config) found a real, pre-existing gap outside this
change's diff, not a defect introduced by it.

This is mergeable as-is on the strength of the code itself. It is not unconditional: **P1-F1
must be checked at merge time** — confirm the merge path is a genuine 3-way merge (standard PR
merge) into a target already containing `7cdba73`, and that `docs/plans/orbital-drift-alignment/PLAN.md`
survives — because the specific comparison this review was asked to trust
(`git diff 7cdba73 HEAD`) is not actually a valid ancestor-diff for this branch, a fact that
was not evident without checking. P2-F1 (the `v0.8.0` pre-commit drift) and the remaining
low/informational items are legitimate follow-ups for later, not merge blockers.
