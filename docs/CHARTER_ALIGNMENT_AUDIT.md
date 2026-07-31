# Charter Alignment Audit

**Scope:** every checkable claim in [`docs/CHARTER.md`](CHARTER.md) verified against the
actual code, configuration, and CI as of this audit — a superset of
[`scripts/check_charter_drift.py`](../scripts/check_charter_drift.py), which only checks
that the charter's markdown links resolve. This audit is **read-only**: it changes nothing
in the charter, code, or other governance docs. Per charter §6, anything that would mean
expanding scope or relaxing an invariant is escalated for a human decision rather than
silently patched — see [Findings requiring escalation](#findings-requiring-escalation).

**Legend:** ✅ CONFIRMED · ⚠️ DRIFTED (claim no longer matches code, needs a decision) ·
❌ VIOLATED · ❔ UNVERIFIABLE (couldn't be checked from repo contents alone)

## 0. Structural link check

`python scripts/check_charter_drift.py -v` — **OK**, all 22 local link targets in the
charter resolve to real files/directories. No dead references.

## 1. §2 Mission — five package roles

| Package | Claim | Verdict | Evidence |
|---|---|---|---|
| `eval_harness` | Exists at `src/`, root package | ✅ | `pyproject.toml:6` `name = "langfuse-eval-harness"` |
| `eval_harness` | Pluggable judges/scorers/sinks/datasets via registry | ✅ | `src/eval_harness/plugins.py:18-24` (`SCORERS/DATASETS/TARGETS/SINKS/JUDGES` registries, `eval_harness.plugins` entry-point group); `src/eval_harness/core/registry.py:20-49` |
| `eval_harness` | Langfuse/Phoenix behind SDK-optional seams | ✅ | `src/eval_harness/langfuse_client/__init__.py`, `phoenix_client/__init__.py` — `import langfuse`/`phoenix` wrapped in `try/except ImportError` |
| `agent-core` | Exists, zero runtime dependencies | ✅ | `agent-core/pyproject.toml` `[project]` has no `dependencies` key at all — only a `dev` extra |
| `agent-core` | Two-gate verifier loop / cost budget / calibration stack via `Protocol` seams | ❔ | Not source-verified this pass (README/AGENTS.md corroborate the module names, but `agent_core/*.py` wasn't opened for `Protocol` typing or "two-gate" terminology) — recommend a follow-up grep before treating as fully confirmed |
| `behavioral-regression` | Exists, calibrated offline ship/hold/escalate gate, judge self-validation | ✅ | `behavioral-regression/pyproject.toml:8`, `README.md:5-9` match near-verbatim |
| `flow-corpus` | Exists, calibrated corpus (specimens/suites/oracles/runner, offline+deterministic) | ✅ | `flow-corpus/pyproject.toml:8`, `README.md:1-9` |
| `flow-protocol` | Exists, versioned contract surface | ✅ | `flow-protocol/pyproject.toml:8`, `README.md:1-9` |
| `scripts/` | Contains quality-gate tooling | ✅ | `scripts/validate.py`, `check_charter_drift.py`, `check_protected_changes.py`, `check_size_budget.py`, `.coveragerc` |
| `skills/` | Vendored, registered via skill marketplace | ✅ | `skills/marketplace.yaml`, `skills/marketplace.schema.json`, `scripts/skill_marketplace.py` |
| AGENTS.md cross-check | "Authoritative table" matches charter's 5-package framing | ✅ | AGENTS.md's per-package table is directionally identical to charter §2 (adds detail, doesn't contradict) |

**Section verdict:** confirmed for all 5 packages and the two supporting directories, with
one open item (`agent-core`'s Protocol/two-gate claims) flagged for follow-up rather than
confirmed drift.

## 2. §3 Scope — non-goal exclusions

| # | Claim | Verdict | Evidence |
|---|---|---|---|
| 1 | Not a training/fine-tuning/RLHF pipeline | ✅ | No `.backward()`/`optimizer.step`/weight-update code outside `claude-foundation/` |
| 2 | Gates never run live evaluations | ✅ | `scripts/regression_gate.py:5-16` — diff-only by design, no judge/Langfuse imports |
| 3 | Auto-fix loop ships disabled | ✅ | `scripts/fix_loop.py:35` `FIX_ENABLED = False`; only referenced in CI as a *test* target, never as a pipeline step |
| 4 | Auto-merge off by default | ✅ | `.github/workflows/calibrated-merge-gate.yml:27` gated on `vars.ENABLE_CALIBRATED_AUTOMERGE == 'true'`; ADR 0005's "flip on" checklist item is unchecked |
| 5 | `claude-foundation` consumed as a pinned plugin, never vendored | ⚠️ **DRIFTED** | See [Findings requiring escalation](#findings-requiring-escalation) §1 |
| 6 | `SCHEMA_VERSION` bumps only in dedicated release commits w/ migration code | ✅ | `src/eval_harness/version.py:16`; sole historical bump (`367a2a4`) paired with a migration in `config/migrations.py` |
| 7 | No permissive config parsing (`from_dict` strict) | ✅ | `agent-core/agent_core/config.py:199-224` and `behavioral-regression/behavioral_regression/config.py:188-196` both raise on unknown keys |
| 8 | Offline suite depends on nothing external | ✅ | All Langfuse/OpenAI/Anthropic/Bedrock SDK imports are deferred + `try/except ImportError` guarded (e.g. `judges/__init__.py:56-60`, `targets/model.py:106-123`) |

**Section verdict:** 7 of 8 confirmed; 1 drifted (claude-foundation vendoring — escalation item).

## 3. §4 Invariants — 7 rules + eval integrity

| # | Invariant | Verdict | Evidence |
|---|---|---|---|
| 1 | Open/closed extensibility via registries/entry points | ✅ | `plugins.py:24` `eval_harness.plugins` entry-point group; decorator-based `Registry` in `core/registry.py` |
| 2 | Versioned, backward-compatible surface (`SCHEMA_VERSION` + migrations + aliasing) | ✅ | `version.py:18`; chained migration registry in `config/migrations.py`; alias resolution in `core/registry.py:26-42` |
| 3 | Dependency injection via `Protocol` (Judge/Scorer/Sink/Clock) | ⚠️ **DRIFTED** | See [Findings requiring escalation](#findings-requiring-escalation) §2 |
| 4 | Stateful I/O confined to narrow seams; scorers/codecs stay pure | ✅ (spot check) | `scorers/__init__.py` (316 lines) has no network/file I/O; `sinks/__init__.py` delegates I/O to SDK client objects |
| 5 | Config-driven, no magic numbers | ⚠️ **DRIFTED** | See [Findings requiring escalation](#findings-requiring-escalation) §3 |
| 6 | Quality gates non-negotiable (coverage floors, ruff/mypy/pytest green) | ✅ | Coverage floors set in all 5 packages' `pyproject.toml` (96/95/95/95/95) + `scripts/.coveragerc` (85); each has a dedicated CI workflow running `make check` |
| 7 | No secrets, no machine fingerprints | ✅ (sanity check) | `.gitignore:45-48` excludes `.env*` except `.env.example`; broad secret-pattern grep across tracked files returned zero hits |
| — | Eval integrity: protected paths require `eval-change-approved` label | ✅ | `scripts/eval_protected_paths.py` defines the protected set; `.github/workflows/quality-gates.yml:150-166` enforces the label via `scripts/check_protected_changes.py` |

**Section verdict:** 6 of 8 confirmed; 2 drifted (Protocol-based DI, config-driven values — both escalation items).

## 4. Ratified Amendments — 8 ADR-linked features

| # | Amendment | Verdict | Evidence |
|---|---|---|---|
| 1 | Calibrated auto-merge gate (opt-in, default-off) | ✅ | `.github/workflows/calibrated-merge-gate.yml:27,66` |
| 2 | Langfuse judge-prompt management (opt-in, YAML fallback) | ✅ | `src/eval_harness/config/models.py:124,273`; `prompts.py` |
| 3 | Multi-model comparison (additive, opt-in) | ✅ | `config/models.py:174,181,276`; `comparison.py` |
| 4 | A/B eval campaigns (additive, opt-in) | ✅ | `config/models.py:212,277`; `campaign.py` |
| 5 | Real model-backed target (additive, opt-in) | ✅ | `targets/model.py` — `@TARGETS.register("model", ...)` |
| 6 | Time-windowed judge rate limiting (additive, opt-in) | ✅ | `config/models.py:82,88,93,119-120` — both fields default `None` |
| 7 | Merge-gate outcome-store persistence (orphan data branch) | ✅ | `agent-core/agent_core/store_sync/models.py:19`, `git_sync.py:97-126` |
| 8 | Structural size-budget enforcement (gate hard, warn soft) | ✅ | `scripts/check_size_budget.py:191,203,207`; ruff `C901`/mccabe in `pyproject.toml:109,115` |

**Section verdict:** all 8 confirmed — every amendment's ADR exists, its feature is
implemented, and it is genuinely opt-in/default-off. No drift.

## 5. §5 Roadmap vs. reality

| Roadmap theme | State | Note |
|---|---|---|
| Merge-gate maturation → enablement | IN-PROGRESS | Stale precondition — see [Findings requiring escalation](#findings-requiring-escalation) §4 |
| Extract `claude-foundation` to its own repo | NOT-STARTED (extraction); staging (M0–M6) done in-tree | Tied to the vendoring drift above |
| Make quality gates required branch-protection checks | NOT-STARTED / UNVERIFIABLE | Branch-protection settings aren't visible from repo contents |
| Enable the auto-fix loop | NOT-STARTED | `FIX_ENABLED = False`; ADR 0004 checklist entirely unchecked |
| Security hardening (Snyk Code / SAST) | NOT-STARTED | No `snyk` references in any workflow |
| E2E harness → nightly CI + Windows parity | IN-PROGRESS | Harness itself is cross-platform (`NEXT_STEPS.md` shows it landed); nightly job and Windows-pinned goldens still open |

None of these are drift by themselves (the charter frames them as forward-looking, and
"not yet done" is consistent with that) — except the merge-gate item, which is listed below.

## 6. Cross-document consistency

`README.md` and `AGENTS.md` are current and consistent with the charter. `GOVERNANCE.md`
correctly describes the charter's role and the §6 escalation process. One real
contradiction was found — see [Findings requiring escalation](#findings-requiring-escalation) §5.

---

## Findings requiring escalation

Five items where the charter's claim and the code's actual state have diverged. None of
these were fixed as part of this audit — per charter §6, scope/invariant questions are a
human decision.

### 1. `claude-foundation/` is fully vendored, not pinned (§3 scope)

The charter and ADR 0017 both state `claude-foundation` is consumed as a pinned plugin
("installing... pinned to a semver `ref`/`sha`, never by vendoring files") and that "no
code changes here until the plugin's v1.0.0 exists." In reality, `claude-foundation/` is a
55-file, fully git-tracked copy (not a submodule, not gitignored), added the same day as
ADR 0017 (`c733fdf`, 2026-07-03). `CHANGELOG.md` and `.github/workflows/claude-foundation-ci.yml`
frame this as a deliberate *staging* directory — building the plugin in-repo before
extracting it — which is a defensible reading, but it's in tension with the ADR's literal
text and the charter's "never vendored" wording, and `skills/marketplace.yaml` has no
pinned-install entry for it yet either. **Decision needed:** either the charter/ADR should
be updated to describe the staging-then-extract pattern explicitly, or the extraction
(roadmap item 2) should be prioritized to resolve the drift.

### 2. Judge/Scorer/Sink are ABCs, not `Protocol`s; `Clock` doesn't exist (§4 invariant 3)

Charter invariant 3 claims "Judge/Scorer/Sink/Clock... are structural" `Protocol` seams.
In code, `src/eval_harness/core/interfaces.py` defines `Scorer`, `DatasetSource`,
`TargetRunner`, `ResultSink`, and `Judge` as nominal `abc.ABC` subclasses with
`@abstractmethod` — not `typing.Protocol`. No `Clock` class or protocol exists anywhere in
the repo. The DI-via-fakes behavior itself does hold (tests inject fakes, not real SDKs).
**Decision needed:** either relax the invariant's wording from "Protocol" to "structural
interface (ABC or Protocol)," or treat this as a backlog item to migrate these ABCs to
`Protocol` and add a `Clock` seam.

### 3. `ModelTarget` hardcodes operational defaults outside a `*Config` class (§4 invariant 5)

Charter invariant 5 claims "every operational value is a `*Config` field with a documented
default; no hard-coded numeric defaults at call sites." `src/eval_harness/targets/model.py:64-71`
hardcodes `max_tokens=1024`, `max_retries=5`, `retry_min_seconds=2.0`,
`retry_max_seconds=30.0` directly on the constructor; target configuration in
`config/models.py:21` is a generic `params: dict[str, Any]` bag rather than a typed
`ModelTargetConfig`. This was a single-module spot check, not an exhaustive scan — other
modules may have similar gaps. **Decision needed:** either scope a fix to introduce a
`ModelTargetConfig`, or note this as an accepted, documented exception.

### 4. Roadmap's merge-gate precondition is stale (§5 roadmap)

The charter says merge-gate enablement is blocked until "agent domains stay cold-start
until an agent-confidence artifact exists." `NEXT_STEPS.md` indicates that artifact
(F-042, `scripts/agent_confidence.py`) has already landed — only HUMAN_AUDIT label
accumulation remains open. The charter's roadmap prose hasn't been updated to reflect
this. **Decision needed:** low-stakes wording update to §5 (not a scope/invariant change,
so this one is closer to routine charter maintenance than an escalation, but flagged here
since it wasn't auto-fixed).

### 5. `HARNESS_SPEC.md` contradicts the charter while `GOVERNANCE.md` still calls it canonical

`GOVERNANCE.md:35` asserts "the canonical spec is `HARNESS_SPEC.md`." But
`HARNESS_SPEC.md` describes a stale, single-package project: a directory tree under
`src/langfuse_eval_harness/` (not the current 5-package layout), only ADRs 0001–0003, a
four-item invariant list that shares no items with the charter's seven, and a non-goals
list ("cloud deployment," "mobile frontend") that shares no items with the charter's eight
scope exclusions. This is the most significant single finding — a document that
`GOVERNANCE.md` names authoritative is factually wrong about current package structure,
invariants, and scope. **Decision needed:** either retire/rewrite `HARNESS_SPEC.md` to
match the charter, or update `GOVERNANCE.md` to stop calling it canonical.

---

*Generated by an automated charter-alignment audit (Claude Code) on 2026-07-31. Structural
link-checking is covered by `scripts/check_charter_drift.py` in CI; this deeper semantic
audit is not currently automated and should be re-run periodically or after major
refactors.*
