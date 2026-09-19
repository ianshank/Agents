# Branch hardening — gap analysis and remediation plan

> The quality machinery in this repo is extensive, well-reasoned and largely excellent.
> Its problem is not missing gates. It is **gates that do not gate**.

## How to read this

Six parallel audits ran against `claude/agent-md-documentation-5qytvj`: code hygiene, test
coverage, tooling/wiring, documentation currency, automation opportunities, and an
adversarial peer review of the branch itself. Every finding below was **independently
re-verified** before it was written down; findings that did not survive verification were
dropped, and two of my own first-pass conclusions were wrong and are recorded as such in §7.

Sizes are S (under an hour), M (half a day), L (multi-day). Every item states whether it
needs the `eval-change-approved` label, because that — not effort — is what determines
sequencing here.

---

## 1. What is already healthy

Stated first, so the rest is not read as a general indictment. These were checked, not assumed:

- **Zero** real `TODO`/`FIXME`/`HACK`/`XXX` markers across 753 Python files.
- 25 `# type: ignore` and 46 `# noqa` repo-wide; exactly one bare ignore without an error code.
- No bare `except:`, no mutable default arguments, no `os.environ.clear()` in tests, no
  hard-coded secrets, no hard-coded absolute paths, no dead code, no stale re-export shims.
- All five packages carry frozen `public_surface_baseline.json` files, so backwards
  compatibility is mechanically guarded, not aspirational.
- Coverage floors are declarative in `coverage-floors.yaml`, and lowering one requires a
  CODEOWNER review by construction.
- `ruff`, `ruff format`, and `mypy` over `src/`, `scripts/` and `tests/` are all clean.
  All nine copies of the `ruff==0.15.20` / `mypy==2.1.0` pins agree.
- Logging discipline is good: 142 of 222 substantial modules carry a logger, and only **5**
  of the remainder touch external I/O. The rest are pure maths or type definitions where a
  logger would be noise.
- `check_skill_script_drift.py` 20/20, `skill_marketplace.py validate` OK, all 19 skills
  pass structural validation, `architecture.mmd` is current, `check_agents_md.py` 47/47.

The debt is concentrated in **enforcement reachability**, not in code quality.

---

## 2. The through-line: gates that do not gate

Twelve separate mechanisms exist, are documented, pass their own checks, and enforce nothing.
This is the single most important finding in the audit, and it is a pattern rather than a
list of accidents.

| Mechanism | Why it does not gate | Fixed? |
|---|---|---|
| `.githooks/pre-commit` | Mode `100644`. Git skips a non-executable hook **silently**. Every contributor who ran `make install-hooks` had a Tier A gate that never fired. Invisible on Windows, where `core.fileMode=false` makes everything look executable. | ✅ `abbb3ea` |
| `scripts/validations/F_049.py` | Guards `DEFAULT_N_BINS` on two of the four histogram signatures — and the two it skips are the two that drifted back to a literal `10`. The gate's blind spot is exactly where the regression is. | §3.1 |
| `scripts/check_agents_md.py` | In no workflow and no `make` target. Reachable only by typing it. | §3.2 |
| `scripts/verify_tier_a.py` | In no workflow. No test file. Its gate list covers 3 of 4 corpora. | §3.2 |
| `scripts/check_branch_protection.py` | No caller anywhere — not a workflow, not the Makefile, not a hook. | §5 |
| `quality-gates.yml` `push:` filter | 12 patterns short of its own `pull_request:` filter, so a direct push to `main` runs no protected-path guard. `check_guard_reachability.py` cannot see this: it parses `on.pull_request.paths` only. | §4.1 |
| `Dockerfile` | Matches no `paths:` filter in any workflow. No CI job builds the image. A Dockerfile that does not build merges green. | §4.1 |
| `uv.lock` | What CI actually installs from, and **nothing watches it**. Dependabot has no `uv` ecosystem, so every pip PR lands red on `uv lock --check`. | §4.2 |
| `skills/README.md` | Hand-maintained, already stale, and checked by nothing. | §4.3 |
| `.agents/` ↔ `.claude/` duplicates | Byte-identical today, with no guard. `.agents/` is never read by Claude Code at all. | §5 |
| `claude-foundation` plugin | **Not loaded in this repo.** Its 4 agents, 4 skills and 3 hooks — including a fail-closed `PreToolUse` guard — never execute. | §5 |
| `.claude/agents/*.md` frontmatter | No validation of any kind. `merge-gate-auditor.md` has **no frontmatter at all**, so it is not dispatchable. | §5 |

---

## 3. Workstream A — close the gate holes (no label needed)

These land without `eval-change-approved`. Do them first: highest value, lowest friction.

### 3.1 `DEFAULT_N_BINS` drift and the guard that misses it — **S**

`agent-core/agent_core/calibration.py:68` promises *"Every histogram signature below defaults
to it so the implementations that must agree cannot silently drift apart the way three
independently re-typed `10`s did."* Lines 80 and 108 honour it. Lines **120 and 148 do not** —
`maximum_calibration_error` and `brier_decomposition` re-type the literal.

`scripts/validations/F_049.py:285` iterates `("reliability_bins", "expected_calibration_error")`.

Fix: replace both literals with `DEFAULT_N_BINS`; extend the F_049 loop to all four names.
⚠️ `scripts/validations/**` is protected — **the F_049 half needs the label**; the
`calibration.py` half does not. Split accordingly.

### 3.2 Wire the guards that run nowhere — **S**

`scripts/verify_tier_a.py` is **not** a protected path. It is the one route that needs no label:

- Add `("AGENTS.md Coverage", [py, "scripts/check_agents_md.py"])` to its gate list.
- Add `("Answer-Quality Corpus Freshness", [py, "scripts/gen_answer_quality_corpus.py", "--check"])`
  — Tier A gates 3 of 4 corpora; the Stop hook and `make corpus-check` both have the fourth.

Ripple: "11 gates" → "12" (or 13) in `README.md:293`, `README.md:310`,
`docs/c4_architecture.md:461`, `AGENTS.md:155`, `CHANGELOG.md`, `NEXT_STEPS.md`. **M** for the ripple.

### 3.3 Stop-hook coverage — **S**

`_CHECKERS` in `.claude/hooks/stop-generated-artifacts.py` omits two artifacts with real
`--check` commands, both measured cheap against the sweep's 1.56 s budget:

- `architecture.mmd` via `mermaid_gen.py --check` — **0.07 s**
- README registry tables via `extract_registries.py --check` — **0.21 s**

Deliberately **not** added: `gen_makefile.py --check` and `gen_gate.py --check`. Both report
stale on a clean tree today, because the root Makefile is documented as hand-extendable.
Adding them installs a permanent false positive and trains people to ignore the hook.

### 3.4 `makegen` under-measures coverage — **M**

`skills/project-setup/scripts/makegen/detect.py:141` does `src = str(source[0])`, dropping
every source after the first while still emitting the full `--cov-fail-under`. Its own forked
sibling documents this exact bug: `skills/quality-gate/scripts/gategen/detect.py:96` says
taking `source[0]` *"would silently measure a subset — a gate-weakening bug, not a
simplification."* Port gategen's tuple-valued detection, repeat-the-flag rendering, and
`COVERAGE_RCFILE` guard into makegen.

### 3.5 Validator swallows malformed YAML — **S**

`skills/common/skill_validator.py:53` wraps `yaml.safe_load` in `except Exception: pass` and
falls through to a hand-rolled line splitter. *"yaml not installed"* and *"the frontmatter is
syntactically invalid"* take the same silent path, so a skill with broken frontmatter is
mis-parsed into a plausible dict and **passes validation**. Catch `ImportError` separately;
let `yaml.YAMLError` surface.

### 3.6 Hard-coded production endpoint — **S**

`skills/openai-judge/scripts/run.py:18` hard-codes `https://integrate.api.nvidia.com/v1` and a
model id as CLI defaults — the only hard-coded third-party production endpoint in the repo,
and a direct violation of the root `AGENTS.md` rule. The sibling convention is right there:
`src/eval_harness/judges/anthropic.py:16` hoists `DEFAULT_ANTHROPIC_JUDGE_MODEL` to a module
constant whose docstring says *"overridable via config — never hard-coded at a call site."*

### 3.7 Unbounded subprocess calls — **M**

Eight `subprocess.run` sites in `scripts/` have no `timeout=`, despite
`agent_core/subprocess_util.py::run_failsafe` existing for exactly this and being importable
from `scripts/` (one migration already does). The two that matter:
`scripts/regression_gate.py:258` (`git worktree add`, the call most likely to block) and
`scripts/validate.py:234`, which runs `shell=True` on an arbitrary `validation_command` string
from `features.yaml` — one bad entry wedges CI indefinitely.

### 3.8 Corpus-generator duplication with a false comment — **S**

`bucket()` exists in four copies across `scripts/`, three of which claim to mirror
`flow_corpus.partition`. They fold **32 bits**; `partition.py` folds **64**. The comment is
the defect: a future reader "harmonizing" a copy to genuinely match would silently reshuffle
every frozen corpus split and break all four `--check` gates. `item_hash` is worse — four
copies with **three different serializations**. Fold into `scripts/_corpus_partition.py` and
correct the docstrings to *"same construction, 32-bit fold — deliberately not bit-identical."*

### 3.9 Unprotected config hygiene — **S each**

- **`.dockerignore`**: patterns are root-anchored, so `__pycache__/`, `*.egg-info/`,
  `.mypy_cache/` etc. exclude only root-level entries. **91 nested cache dirs survive**; two
  land inside the image via `COPY src/ src/`. Build context ≈ **124 MB** for an image needing
  ~2 MB. Prefix with `**/`, add the sibling packages, `tests/`, `corpora/`.
- **`.gitleaks.toml:23`**: allowlists `skills/repo-invariant-review/evals/fixtures/.*`,
  justified by a `scripts/build_fixture.py`. **Neither exists.** A standing unanchored
  whole-subtree suppression for a path anyone can create. Delete it; anchor `\.env\.example$`
  to `^\.env\.example$`.
- **`.gitignore:99-106`**: bare unanchored filenames (`context.json`, `agent.json`,
  `merge_outcomes.jsonl`, …) match at **any depth**. Verified: `config/context.json` and
  `tests/fixtures/agent.json` are ignored — both under protected eval-integrity roots. A new
  eval fixture with one of those names is silently never committed. Anchor them with `/`.
  Separately add `*.log`, `coverage.xml`.

---

## 4. Workstream B — CI and dependency wiring (needs the label)

Everything here touches `.github/**`. Group into **one** labeled PR.

### 4.1 Filters that do not cover what they claim — **S each**

- `quality-gates.yml` `push.paths` ⊂ `pull_request.paths` by 12 patterns, including
  `config/**`, `architecture.yaml`, `coverage-floors.yaml`, all six `Makefile`s and the five
  sibling `tests/**` roots. Anything reaching `main` outside a PR runs no protected-path guard.
  Also extend `check_guard_reachability.py` to parse both triggers, so this cannot recur.
- `Dockerfile` is in no filter and no build job. Add a build step; digest-pin
  `FROM python:3.11-slim` (the repo's *other* Dockerfile is digest-pinned under a comment
  reading *"like every other image"*).
- `skills-ci.yml` filters on `skills/**` only, yet installs `-e ../..` and `-e ../../agent-core`.
- `architecture-drift.yml` omits `claude-foundation/**`.
- `pip-audit.yml` omits `requirements.txt` and `experiments/backend-validation/pyproject.toml`.

### 4.2 Dependabot cannot do its job — **M**

`uv.lock` (132 packages) is what CI installs from and is watched by nothing. Add
`package-ecosystem: uv` at `/` (covers the workspace root and all five members, updating
`pyproject.toml` + `uv.lock` together) and retire the per-member pip entries. Add
`package-ecosystem: docker`. Without this, every dependency PR arrives red and gets ignored —
the exact failure the config's own header says it exists to prevent.

### 4.3 The three unregistered skills — **S–M**

`corpus-guardian`, `e2e-matrix-sentinel` and `refactoring-decomposer` are registered in
`marketplace.yaml` but have no `skills-ci.yml` job and no `ci_exempt.yaml` entry. **This is
failing CI on the current PR.** They cannot be exempted: ADR 0030 scopes exemption to
subjective skills with no `evals/`, and all three ship `evals/evals.json` — the guard rejects
a stale exemption for precisely that reason. Each needs a job block copied from `dataset-lint`,
plus a `tests/` directory to clear the ≥95% floor (all three currently ship `SKILL.md` +
one script + `evals/` and nothing else).

### 4.4 Also in this PR — **S**

Wire `check_agents_md.py` into `docs.yml`'s `doc-structure guards` job. The pytest suite does
exercise it, but under `eval-harness-ci.yml`, whose filter excludes `skills/**`, `docs/**` and
`.agents/**` — the very directories whose `AGENTS.md` files it guards. Promote `docs.yml`'s
relative-link job from advisory to blocking: the most recent commit on this branch is literally
a fix for what that job found, which is proof it catches real defects and proof nobody is
compelled to act on them.

---

## 5. Workstream C — agents, skills, hooks, loops

### 5.1 The plugin is not loaded — **verify, then decide** — **S**

`claude-foundation`'s 4 agents, 4 skills and 3 hooks (including a **fail-closed** `PreToolUse`
guard) never execute here: `~/.claude/plugins/` has no entry, `.claude/settings.json` declares
no `enabledPlugins`, and the repo's own detector reports `recommended_path: degraded`. So the
`explorer`/`test-runner` divergence between `.claude/` and `claude-foundation/` is moot —
one side is dead. Decide explicitly: load the plugin, or document that root owns everything.

### 5.2 No agent-frontmatter validation — **S**

Nothing reads `.claude/agents/*.md` frontmatter — not a test, not a script. That is how
`merge-gate-auditor.md` came to have **none at all**, making it undispatchable. Add
`tests/test_claude_agents.py`: parse every definition, require `name` matching the filename, a
non-empty `description`, and `tools` drawn from an allowlist. Also drop `effort:` from
`explorer` and `narrow-critic` unless something can be shown to read it. ⚠️ `tests/**` protected.

### 5.3 Sync guard for the duplicated trees — **S**

`.agents/agents/merge-gate-auditor.md` and `.agents/skills/update-executive-report/` are
byte-identical to their `.claude/` counterparts with nothing keeping them so. Append a
parametrized byte-identity test to `tests/test_claude_hooks.py` (which already reads
`.agents/`), deriving the pair list by walking the tree so future duplicates are covered on
arrival. ⚠️ `tests/**` protected.

### 5.4 Skills worth building — **M each**, in value order

1. **`skill-scaffold`** — the "adding a skill" procedure failed three-for-three
   (`corpus-guardian`, `e2e-matrix-sentinel`, `refactoring-decomposer` each shipped without
   `tests/`, `ruff.toml`, `quality-gate.sh`, a vendored validator, or a CI job). Three
   consecutive failures of a written procedure is the definition of something that should be
   executable. A bare script cannot decide job-vs-EXEMPT; the skill can, from whether
   `evals/evals.json` exists.
2. **`component-registration`** — 54 registered components; six steps, five files, three
   independent gates, prose-only today.
3. **`agents-md-author`** — 47 files against a seven-check mechanical contract that already
   has a checker; the skill is a scaffolder plus a repair loop around `--json`.
4. **`merge-gate-auditor`** — the SKILL.md is **already written**, in `.agents/`, the one tree
   Claude Code never reads. Move it to `skills/`, register it, and split the contract honestly:
   card rendering is eval-gatable, the verdict must assert **refusal**.

### 5.5 Subagents worth adding — **S each**

`drift-sentinel` (reconciles the derived/duplicated pairs; needs `Bash`, so not `explorer`) and
`registry-matrix-reviewer` (ADR 0032 matrix obligation on registry diffs). Both read-only:
regeneration writes to protected paths and must go through review.

### 5.6 Hooks — **S each**

- PostToolUse on `**/AGENTS.md` → `check_agents_md.py`. Measured **0.078 s** for the whole
  repo. Complements §4.4; neither alone is sufficient.
- PreToolUse `Bash` deny-list, **fail-closed** — five literal patterns that exist today only
  as prose: `main:main` refspecs, force-push to `main`/`merge-gate-data`, `--cov-fail-under`
  below the pin, `--no-cov`, `check_branch_protection.py --apply` from an agent session.
  Fail-closed is defensible precisely because it is a literal deny-list, not a judgment.
- Keep all four existing hooks **fail-open**. The recorded reasoning holds: the protected-path
  rule governs *who reviews*, not whether the edit may be written; size-budget and registry
  drift fire mid-refactor by construction. The right fail-closed point is the commit boundary,
  which is `.githooks/pre-commit` — now actually executable.

### 5.7 Loops — **S unless noted**

| Loop | Today | Should be |
|---|---|---|
| Dependency audit | `pip-audit.yml` has no `schedule:` — a CVE against an unchanged pin is never surfaced | weekly cron, report-only, opening one tracking issue |
| Branch-protection soak | nothing; the runbook's "five green runs" is counted by hand | weekly `--probe --strict`, never `--apply` |
| Skills-registry drift | nothing; `skills/README.md` is already stale | generate the table from `marketplace.yaml`, matching the `extract_registries.py` precedent |
| Merge-gate cadence | correctly designed, but nothing notices a **stalled** loop — silence looks identical to progress | fail when 0 candidates selected for N weeks, or `remaining_by_domain` is unmoved for 4 (**M**) |
| Coverage-floor ratchet | `check_coverage_floors.py` refuses lowering; nothing ever proposes raising | monthly PR — never a push — when actual ≥ pin + 2 (**L**) |

---

## 5A. Workstream C2 — testing

Coverage is healthy in aggregate — root 97.57% (floor 96), agent-core 97.77%, and
behavioral-regression / flow-corpus / flow-protocol all at **100%**. That number is also the
problem: it is high enough to hide what it cannot see.

### 5A.1 The coverage gate cannot see the sandbox — **M**

`src/eval_harness/targets/_suite_runner.py:113-115` is the `setrlimit` call that applies
*every* sandbox limit. It reports as uncovered because `_apply_sandbox_limits()` only ever
runs **in the subprocess**, where coverage.py is not collecting. So the child-side half of the
ADR 0045 sandbox contributes **nothing** to the 96% floor — the floor is satisfied entirely by
the parent-side `_sandbox.py`. Two subprocess tests exercise it behaviourally, and one of the
two is the broken test in §5A.2.

The coverage gate is the repo's stated evidence that the sandbox works, and it is blind to it.
Fix with an in-sandbox probe suite that asserts the child bound the parent's limits (this is
coverage-visible and provable at any uid), or enable `COVERAGE_PROCESS_START` for the child.

### 5A.2 The fork-bomb test, root-caused — **M**

`tests/test_testgen_target.py:141` is not flaky. `RLIMIT_NPROC` is enforced per real-UID and
**bypassed for `CAP_SYS_ADMIN`/`CAP_SYS_RESOURCE`**, which root holds. I reproduced it: as
uid 0, `setrlimit(RLIMIT_NPROC, (0,0))` succeeds, `getrlimit` confirms `(0,0)`, and `os.fork()`
succeeds anyway. It passes on GitHub's `ubuntu-latest` because that runs as non-root.

The test's guard is `pytest.importorskip("resource")` — which answers *"does this platform have
rlimits?"*, the wrong question. The right one is *"will this uid have them enforced?"*

The fix is to split a conflated claim, not to weaken one. The test currently asserts two
independent propositions: (1) the parent hands `RLIMIT_NPROC=0` to the child and the child
binds it before loading model-authored code — **this repo's half, provable at any uid**; and
(2) a `fork()` under that limit is denied — **the kernel's half**. Assert (1) unconditionally;
gate (2) on a capability probe that forks once in a throwaway subprocess and skips with an
honest reason. Nothing is weakened: the assertion that today silently vanishes on Windows
starts running everywhere.

### 5A.3 A test that would pass if the implementation were deleted — **M**

`tests/test_parallel_execution.py:129` asserts `call_count <= 10` over a 10-item run where
`_run_one` is called at most once per item by construction. It is a tautology — the comment
above it concedes the property is not assertable as written. Delete `fail_fast`'s
`executor.shutdown(cancel_futures=True)` and the test stays green. Make the remaining items
block on a `threading.Event` the test never sets, then assert `call_count < 10` strictly.

Worth noting for balance: this is the **only** such test found. Mock-assertion discipline is
genuinely good — 27 `assert_called*` sites across ~3,500 tests — there are no untracked skips,
and the single `xfail` is `strict=True` with a documented threat model.

### 5A.4 Skill coverage floors are unpinned — **S**

`coverage-floors.yaml` has **no `skills` unit** — verified, zero matches. Fifteen of 19 skills
declare `--cov-fail-under=95` in their own generated gate, and `check_coverage_floors.py`
never reads them. A PR lowering `skills/model-bench` from 95 to 50 needs no label and no
CODEOWNER — precisely the hole that file's header says it exists to close.

### 5A.5 Untested error branches on untrusted input — **M each**

The worst uncovered clusters are all parsers of untrusted input, and they are genuinely
untested logic rather than unreachable defence:

- **`scorers/rca/__init__.py` (71%)** — every malformed-input branch of three readers is dead
  to the suite. `inputs.candidates` as a string rather than a list silently becomes "no
  candidate set", so a corpus typo makes an item unscorable instead of failing loudly. The
  module docstring makes *malformed vs abstained* load-bearing; that distinction has no test.
- **`targets/rca_baseline.py` (79%)** — NaN, inf, `"3"`, a dict, a constant pre-window: none
  tested. The module's own words are that an infinite z would "win every ranking regardless of
  the post window", and no test would notice.
- **`agent_core/ppi.py`** — all nine uncovered statements are the module's own fail-closed
  branches. Its docstring says *"Fail-closed by construction… An interval we cannot trust must
  never render as the tightest one on the page."* The fail-closed behaviour is the one thing
  not tested.
- **`agent_core/calibration.py:175`** — `auroc()`'s length-mismatch raise is untested, and
  AUROC ≥ 0.65 is a **merge-gate activation criterion**. A regression returning a number
  instead of raising would silently manufacture a gate verdict.
- **`cli.py`** — the entire non-`--offline` branch of `run`, `compare` and `campaign record`.
  Every CLI test passes `--offline`.

### 5A.6 Two modules at 0%, and vacuous e2e credit — **S–M**

`scripts/verify_tier_a.py` (44/44 uncovered) and `scripts/seed_langfuse_dataset.py` (41/41) pass
the `scripts/` floor purely on other modules' headroom. Separately,
`tests/test_e2e_matrix.py:803,819` skip when `artifacts/e2e-report/` is absent — and the skip
reason says that is "the normal state in CI". So the two tests that verify the committed e2e
matrix matches a real run **never execute**. Have `nightly-e2e.yml` produce a report and then
run those tests against it, so the guard has somewhere to fire.

### 5A.7 Trust boundaries: well tested, with named residuals — **S each**

`_imports.py` and `_paths.py` are at 100% with 30+ dedicated tests each, including
sibling-prefix and symlink-escape classes. The residuals are worth recording rather than
fixing blindly: `__module__` is attacker-writable, so an allowlisted package can rebind it on a
re-exported `subprocess.call` and defeat the re-export defence (document the limit, or compare
against `inspect.getmodule`); a missing *attribute* raises bare `AttributeError` outside the
refusal taxonomy; a trailing-dot allowlist entry silently denies everything; and `_paths.py`'s
docstring claims cross-platform separator checking that is a no-op on POSIX.

**The gating module is exemplary** — 100%, no uncovered branch, advisory and blocking paths
sharing `_evaluate_rule` verbatim so they cannot drift. The only addition worth making is a
property test that `GateResult.passed` is false iff some non-`report_only` rule is unmet.

---

## 6. Workstream D — documentation currency

### 6.1 Errors already fixed on this branch (`abbb3ea`)

The root `AGENTS.md` duplicated fragment; `CHANGELOG.md`'s "18 top-level components" (17) and
"246 to 199 lines" (176); the unresolvable `EXECUTIVE_BRIEF.md` reference; and this plan's
sibling claiming the guard runs via `make pre-pr` when it does not.

### 6.2 Outstanding — **S each unless noted**

- **`README.md:90`** claims component contracts are *"abstract base classes"*. They are
  `typing.Protocol` — stated in `core/interfaces.py:5`, claimed by `CHARTER.md:169`, and
  **re-checked by `check_charter_invariants.py`**. The README contradicts a CI-enforced
  invariant. Highest-value single-line fix in the repo.
- `README.md:48` says "five installable packages"; the table below it lists six.
- `README.md:546` lists 15 skills; there are 19. `README.md:564` omits `trace-analytics`.
- `skills/README.md` omits three skills and lists `quality-gate` at 1.2.0 vs 1.3.0.
- `experiments/README.md` omits `trace-analytics` — already flagged in prose by this branch's
  own `experiments/AGENTS.md`, which documented the drift instead of closing it.
- `behavioral-regression/__init__.py:8` claims a `flow_protocol` import that does not exist;
  `pyproject.toml:22` declares it as a dependency that is never directly imported.
  ⚠️ the pyproject half is protected.
- `docs/c4_architecture.md`: scorer list says 26, live registry has 29; the L2 container view
  omits `replay` and `flow_protocol` (2 of `architecture.yaml`'s 22 components). Root cause:
  `extract_registries.py` defaults `--docs` to the two READMEs only, so the C4 doc rots
  undetected. Adding it to that default is the durable fix (**M**).
- `CONTRIBUTING.md` tells contributors to run `make check-all` — which the root `AGENTS.md`
  states in terms is *not* the whole CI surface. It never mentions `make pre-pr`. Its
  protected-path list gives ~9 of 36 patterns, omitting `Makefile` and every `pyproject.toml`.
  This is the single most load-bearing doc gap for an external contributor.

### 6.3 An ADR is owed — **M**

The normative `AGENTS.md` rules — the tier model, the 100/80/200 budgets, `COVERED_BY_PARENT`,
"a skill's `SKILL.md` is already its agent contract" — exist only in a **plan**, which
`docs/STYLE.md` classifies as work-scoped and transient. This is a decision with lasting
consequences. Next free number: **ADR 0050**.

### 6.4 An F-ID is owed — **M**, after §3.2 and §4.4

Next free: **F-071**. Filing it today would require asserting a CI clause that is not yet true,
so it belongs in the same labeled PR as the CI wiring, not before. `features.yaml`,
`features.schema.json` and `scripts/validations/**` are all protected.

---

## 7. Corrections to my own analysis

Recorded because an audit that hides its own misses is not an audit.

1. **Logging.** My first pass reported 123 modules missing loggers. The detection string
   missed `agent_core`'s own `get_logger()` wrapper. Correct figures: 142 with, 80 without,
   and only **5** of those touch external I/O.
2. **`subprocess_util.py`.** I listed it as a logging gap. It logs correctly, via that same
   wrapper.
3. **The fork-bomb test.** I characterised it as "a container capability difference". That
   was directionally right but imprecise, and the precise version changes the fix: `RLIMIT_NPROC`
   is enforced per real-UID and bypassed for `CAP_SYS_RESOURCE`, which **root** holds. So it is
   deterministic for uid 0, not environmental luck — and the remedy is to split the conflated
   claim (§5A.2), not the "clean capability skip" I first proposed, which would have skipped
   this repo's half of the assertion along with the kernel's.
4. **`scripts/_agents_md_lib.py` landed at 479/500 lines** — 96% of the budget I added it to
   enforce. Its own docstring says it was split out *to stay inside* the cap, so it was born at
   the ceiling. Seam is already visible: move the per-doc content checks to
   `scripts/_agents_md_checks.py`, leaving tables and orchestration at ~300. **S**, and worth
   doing while the branch is open.

---

## 8. Sequencing

| PR | Contents | Label? |
|---|---|---|
| **1 — unblocked fixes** | §3.1 (calibration half), §3.2, §3.3, §3.5, §3.6, §3.9, §6.2 (unprotected docs) | no |
| **2 — CI and dependencies** | §4.1, §4.2, §4.3, §4.4, §3.1 (F_049 half) | **yes** |
| **3 — tests and agents** | §5.2, §5.3, §6.2 (protected docs), §6.4 (F-071) | **yes** |
| **4 — testing** | §5A.1, §5A.2, §5A.3, §5A.4, §5A.5, §5A.6 | **yes** (`tests/**`) |
| **5 — decomposition** | §3.4, §3.7, §3.8, §7.4, and the oversized test files below | mixed |
| **6 — automation** | §5.4, §5.5, §5.6, §5.7 | mixed |

**The god-file surface nobody guards:** `check_size_budget.py` excludes `tests` via
`EXCLUDED_DIR_NAMES`, so the 500-line cap never applies there. **17 test files exceed it,
totalling 17,250 lines**, led by `tests/test_matrix_eval_tools.py` at **3,583** — 7× the source
budget. This is where decomposition effort actually belongs. ⚠️ `tests/**` protected.

Also worth a decision: ADR 0019 records "41 functions currently exceed 50 physical lines" and
frames the warning class as a burn-down backlog promotable to a hard gate. It is now **108**.
Either re-baseline the ADR and drop the promotion language, or set a ratchet.

## 9. Verification

Every workstream ends with the same bar, and PR 2 onward must also show the gate it adds
failing before it passes:

```bash
python scripts/verify_tier_a.py            # 11 gates (12 after §3.2)
python scripts/check_agents_md.py          # 47 files
make pre-pr                                # the fullest local mirror of CI
python scripts/check_protected_changes.py  # confirms the label requirement
```

## Links

- [`docs/plans/agents-md-directory-docs/PLAN.md`](../agents-md-directory-docs/PLAN.md) — the branch this audits
- [`docs/CHARTER.md`](../../CHARTER.md) — §3 scope, §4 invariants
- [`scripts/eval_protected_paths.py`](../../../scripts/eval_protected_paths.py) — the authoritative protected set
