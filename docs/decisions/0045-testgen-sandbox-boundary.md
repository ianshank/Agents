# 0045 — Testgen sandbox boundary: scrubbed environment + POSIX rlimits now, OS isolation deferred

- Status: **Accepted.**
- Date: 2026-09-06
- Related: ADR 0043 (testgen evaluation seam), ADR 0039 (callable-target allowlist),
  ADR 0038 (item error policy), `src/eval_harness/targets/testgen.py`,
  `src/eval_harness/targets/_sandbox.py`, `src/eval_harness/targets/_suite_runner.py`,
  `openspec/changes/add-agent-in-the-loop-testgen/` (the change this unblocks).

## Context

The testgen target executes test suites in a fresh interpreter subprocess
(`targets/testgen.py` + `targets/_suite_runner.py`). For F-065 the suites came from a
frozen, human-reviewed corpus (`corpora/**` is a protected path), so the subprocess
boundary only needed to guarantee *termination* and *verdict integrity*: cwd
confinement, a wall-clock timeout, path-escape refusal, and a file-carried verdict.

`add-agent-in-the-loop-testgen` removes the human review gate between authorship and
execution: the suite is fresh model output. Reviewing the boundary against that change
surfaced four holes the existing sandbox does not close:

1. **Credential exposure.** The child inherited the whole process environment
   (`subprocess.run` without `env=`), so in any credential-bearing job (a live judge
   run, a live sink) generated code could read and exfiltrate `OPENAI_API_KEY`,
   `LANGFUSE_*`, `AWS_*`, etc. This hole exists **today**, for corpus suites too,
   whenever the harness runs in a credential-bearing process.
2. **No resource limits.** A CPU-bound loop, memory hog, fork bomb, or unbounded file
   write was bounded only by the wall-clock timeout.
3. **No network isolation.** Generated code can open sockets (already documented as a
   test limitation; see `tests/test_testgen_target.py`'s network test).
4. **No filesystem read confinement** (writes are confined; reads are not).

The in-flight spec line "execution does not open sockets"
(`add-agent-in-the-loop-testgen/specs/.../spec.md`) is ambiguous between the harness
and the generated code. This ADR resolves it: the obligation binds the **harness**
(the target opens no socket; verified by the network test's parent-side guard).
Generated-code networking is residual risk, handled below.

## Decision

**Option S3 (hybrid): land the cheap hardening now; defer OS-level isolation behind a
recorded trigger.**

Now (this change):

- **Default-deny child environment.** The sandboxed interpreter inherits only an
  allowlisted plumbing set (`PATH`, `HOME`, `TMPDIR`/`TEMP`/`TMP`, `SYSTEMROOT`,
  `LANG`, `LC_ALL`, `PYTHONUTF8`). The allowlist is a module constant in
  `targets/_sandbox.py`, deliberately **not** config-driven: a config knob would be a
  way to widen what generated code can see, which is the decision this ADR forbids
  delegating.
- **POSIX resource limits**, carried to the child through the scrubbed environment
  (`EVAL_HARNESS_TESTGEN_RLIMIT_*`) and applied by `_suite_runner` to itself before
  loading any model-authored code: CPU seconds (derived from the execution timeout),
  address space, process count (0 — no fork/threads), per-file size, open files.
  Limits travel through the environment rather than `preexec_fn` because
  `preexec_fn` runs between fork and exec, which is unsafe under the engine's
  threaded item execution (`max_workers > 1`); env-carried limits keep the fork path
  lock-free. On platforms without the `resource` module (Windows) the runner logs the
  degradation and the wall-clock timeout remains the only bound — the repo's accepted
  platform-asymmetry posture.
- Limits are fields on `SandboxLimits` with documented defaults (ADR 0009); there is
  no per-item override in v1 (YAGNI — the corpus is synthetic and uniform).

Deferred (recorded trigger, not a silent gap):

- **OS-level network/process isolation** (`unshare -n`, bubblewrap, container-per-run).
  Deferred until the first non-synthetic corpus or the first credential-gated live
  *generation* workflow, whichever comes first. Rationale: it is Linux-only, adds a
  runtime dependency to the offline path, and conflicts with the repo's
  cross-platform CI matrix; the offline CI job carries no secrets, so the marginal
  risk of egress from generated code in that job is accepted in writing here.

Rejected:

- **S1-only without the env scrub** (timeout-only status quo): leaves the credential
  hole open today.
- **S2 now**: disproportionate for a synthetic-corpus, offline-CI capability, and
  unportable.

## Consequences

- F-065 corpus executions also run under the scrub and limits (the hole existed for
  them too). Corpus suites are stdlib-only, so behavior is unchanged; the F-065
  validator and the full testgen suite stay green.
- `add-agent-in-the-loop-testgen` is unblocked on the security dimension: its
  pipeline PRs may proceed with this boundary as the minimum, citing this ADR.
- The network test's docstring now points here as the record of the residual
  network/read risk.
- When the deferral trigger fires, the follow-up ADR must re-evaluate S2 (or
  stronger) before the triggering corpus/workflow lands.
