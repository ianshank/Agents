# 0022 — Determinism boundary for inference skills (consume, don't contain)

- Status: **Accepted.**
- Date: 2026-07-19
- Related: ADR 0017 (claude-foundation reconciliation), ADR 0019 (size-budget gate),
  ADR 0020 (deterministic generator skills), ADR 0021 (CI gate delegation), `skills/quality-gate/` (emits
  `scripts/quality-gate.sh`), `skills/project-setup/` (emits the delegating `Makefile`),
  `skills/architecture-drift-guard/scripts/mermaid_gen.py`,
  `.github/workflows/architecture-drift.yml`,
  `claude-foundation/skills/{plan,test-first,code-review,c4-docs}/SKILL.md`,
  `claude-foundation/hooks/post_edit_verify.py`,
  `scripts/check_skill_script_drift.py` (TRACKED_DUPLICATES).

## Context

ADR 0020 introduced generator skills that turn re-inferred procedure into committed
deterministic artifacts, and the repo has now dogfooded them: every project root (and each
sibling package) carries a generated `scripts/quality-gate.sh` with subcommands
`lint|typecheck|test|coverage|all` — strict bash, single source of truth, `make check`
delegating to it, CI running the same script.

The inference-heavy skills under `claude-foundation/skills/` (plan, test-first,
code-review, c4-docs) predate that artifact and still describe procedures that *re-derive*
the very commands the gate now supplies: plan invents verification commands, test-first
re-detects the test framework, code-review reasons about coverage without ground truth.
Two definitions of "passing" is exactly the drift class ADR 0020 removed, reintroduced one
layer up. At the same time, the opposite failure mode looms: absorbing gate logic *into*
the skills would vendor deterministic code across the foundation boundary (the copy-drift
failure ADR 0017 exists to prevent) and would entangle generic skills with one host repo's
tooling. What is missing is a recorded boundary: which side of the line each concern lives
on, and how the two sides connect.

## Decision

### 1. The consume-don't-contain rule

Inference skills never absorb deterministic logic; they **consume committed artifacts**
produced by generator skills — the quality-gate script, generated diagrams — as inputs and
verification oracles.

The boundary line: everything *below* the gate script — which commands run, which
thresholds apply, in what order — is generator territory, owned by deterministic code and
its committed output. Everything *above* it — what to build, whether a finding matters,
whether a test is honest — stays inference. An inference skill that needs a deterministic
fact reads the artifact (or runs it, where the skill is allowed to run commands); it never
re-derives or restates the artifact's contents in its own prose.

Concretely, three claude-foundation skills gain delegation wording (generic per ADR 0017 —
"if the target project has a `scripts/quality-gate.sh` …", no repo names, no absolute
paths, enforced by `python -m foundation_tools.scan`):

- **plan** — success criteria and the feedback loop are phrased as gate subcommand
  invocations when a gate exists (per-change fast check `./scripts/quality-gate.sh lint`,
  final verification `./scripts/quality-gate.sh all`); inventing parallel tool invocations
  while the gate exists is treated as fabrication. The gate script's `do_*` functions and
  thresholds *are* the enumeration of the repo's enforced style/lint constraints — read
  the script, don't rediscover.
- **test-first** — a present gate script names the test framework (no re-detection);
  suite-wide runs delegate to `./scripts/quality-gate.sh test` / `coverage`; reported
  commands are the stable gate invocations. The red phase is deliberately *not* delegated:
  test-scoped runs stay ad-hoc because the gate is suite-wide by design.
- **code-review** — callers should run `./scripts/quality-gate.sh all` beforehand and pass
  its output in as evidence; the fork itself stays read-only (no Bash). Supplied gate
  output grounds coverage claims in fact; deterministic scanners own regex-detectable
  secrets and hardcoded values, the review hunts the semantic instances.

In every case the fallback is unchanged: when no gate exists, the skills derive commands
from the repository as before.

### 2. Two `--check` conventions, named side by side

The repo now has two deliberately different `--check` semantics, and they must not be
conflated:

- **Fully-derived artifacts gate.** `mermaid_gen.py --check` verifies an artifact that is
  never hand-edited — a pure function of `architecture.yaml` — so a diff is always drift
  and the check runs **blocking** in `.github/workflows/architecture-drift.yml`.
- **Hand-extensible scaffolds advise.** `gen_gate.py --check` and `gen_makefile.py
  --check` diff scaffolds that users are *expected* to extend, so a diff is a signal, not
  a defect; these are **advisory only** and are never wired as blocking CI gates
  (ADR 0020 design law 4).

The routing rule for any future generator: if the artifact is fully derived and
never-hand-edited, its `--check` gates; if it is a hand-extensible scaffold, its `--check`
advises.

### 3. The c4-docs delegation seam

The c4-docs skill's Level 3 (component) view is the layer that decays fastest and is the
most mechanically derivable. Where the host repo has a manifest-driven deterministic
generator for component-level diagrams (as this repo does with `mermaid_gen.py` over
`architecture.yaml`), the skill's L3 step defers to that generator's committed output
instead of hand-drawing a parallel diagram; the skill's judgment stays at scoping (which
subsystem deserves L3 at all) and at drift narration. **This ADR is the single record of
that seam** — a sibling P4 change amends the c4-docs skill text itself; no other document
should restate the seam.

### 4. Considered and deferred

- **Wiring claude-foundation's `post_edit_verify.py` hook to the gate script.** Deferred
  to the post-extraction M7 dogfood PR (ADR 0017). Three reasons: the hook registers only
  via the plugin's `hooks.json`, so this repo cannot adopt it before M7 installs the
  plugin; it is a *per-file* verifier (a `{file}` command template) mismatched to a
  whole-tree gate — running `quality-gate.sh all` after every single edit is the wrong
  granularity; and its no-shell argv exec (`shlex.split`, no shell interpretation) makes a
  `.sh` command a silent no-op on Windows. Recommended M7 shape: a per-file,
  cross-platform command such as `python -m ruff check {file}` via
  `CLAUDE_FOUNDATION_VERIFY_CMD`, leaving the whole-tree gate to explicit invocations.
- **Deriving C4 Level 2 from the architecture manifest.** Deferred. The manifest's edges
  are *import-semantics* (what statically depends on what); the hand-maintained L2
  container diagram's edges are *runtime-semantics* (what talks to what, over which
  protocol). Generating L2 from the manifest would create a second semantics collision —
  one diagram, two incompatible meanings of an arrow — so L2 stays hand-maintained with
  drift flagged, and only L3 delegates (§3).

### 5. Explicit non-goals

- **No vendoring across the foundation boundary** (ADR 0017): the skills reference the
  gate generically; no gate code, thresholds, or repo-specific commands are copied into
  claude-foundation, and nothing from claude-foundation is copied here.
- **No new TRACKED_DUPLICATES entries**: this boundary is prose-and-contract, not another
  vendored file for `check_skill_script_drift.py` to police.
- **No mechanization of judgment**: code-review stays a no-Bash fork (its isolation is
  load-bearing — a reviewer that can run commands can be steered by them); test-first's
  red-phase classification ("failing for the right reason") stays semantic; plan's
  constraint elicitation stays conversational. The gate feeds these judgments facts; it
  does not replace them.

## Consequences

- One definition of "passing" per project, at every layer: the gate script defines it, CI
  runs it, and the inference skills now cite it instead of competing with it. The
  fabricated-parallel-command drift class is closed by contract, not by review vigilance.
- The two `--check` conventions have names and a routing rule, so future generators don't
  relitigate blocking-vs-advisory per PR.
- The c4-docs L3 seam is recorded once, here; the P4 skill amendment implements it without
  needing its own decision record.
- The deferred items (post-edit hook wiring, manifest-derived L2) have recorded reasons
  and a recommended shape, so M7 and any future L2 proposal start from this analysis
  rather than rediscovering the mismatches.
- Cost: three skill contracts grow conditional wording (gate present vs. absent), and
  their evals must cover both routes to keep the fallback honest.
