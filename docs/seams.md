# SDK-optional seams

> Every integration in this repo imports its real dependency lazily, so the package
> installs and the offline suite runs with zero external dependencies.

Extracted from `AGENTS.md` so the per-seam detail is available when an agent is actually
adding or changing a seam, rather than loaded into every session. The rule itself stays in
`AGENTS.md`; this is the roster and the reasoning behind each entry.

## The seams

- `src/eval_harness/core/_trajectory.py` — pure, deterministic tool-call canonicalisation
  (sets sorted by value, unknown types rendered by `type:value`, bounded recursion). No I/O.
- `src/eval_harness/scorers/trajectory.py` — the seven agent-trajectory scorers (F-051).
- `src/eval_harness/langfuse_client/__init__.py` — Langfuse tracing + score export.
- `src/eval_harness/phoenix_client/__init__.py` — Phoenix tracing + score export (mirrors `langfuse_client` deliberately; ROI matrix in `docs/phoenix-spike.md`).
- `src/eval_harness/braintrust_client/__init__.py` — BrainTrust experiment export (`build_client`) + dataset read (`fetch_dataset_items`); mirrors `phoenix_client`, `docs/braintrust-spike.md`.
- `src/eval_harness/judges/*.py` — `MockJudge` (offline default), `OpenAIJudge`, `AnthropicJudge`, `BedrockJudge`, `PhoenixEvalJudge`.
- `src/eval_harness/sinks/__init__.py` — `console`, `json_file`, `html_file`, `langfuse`, `phoenix`, `braintrust`.
- `agent-core/agent_core/proxies.py` — `ProxyExtractor` Protocol + `MappingProxy`. Same shape, different direction: an external score (an LLM judge, a static analyser) is *injected* rather than a client being lazily imported, so `agent_core` measures a judge's signal while staying dependency-free and pure stdlib. Add a proxy here, never a dependency there.
- `agent-core/agent_core/protocols.py` — `Clock` Protocol + `SystemClock`/`FixedClock`. The DI seam for "now": `audit_sampler.record_verdict`, `merge_seed.seed_pending`, `outcome_labeller.label_matured`, and `merge_gate_ci._append_audit` all take an optional `clock: Clock | None = None` instead of calling `datetime.now()` directly, so tests inject a `FixedClock` for determinism without patching `datetime`.
- `src/eval_harness/core/interfaces.py` — `Judge`/`DatasetSource`/`TargetRunner`/`ResultSink`/`Scorer`/`StateAdapter` are `typing.Protocol` (structural DI). Every DI seam is structural: fakes used in tests satisfy interfaces by shape alone without inheritance, while existing nominal subclasses keep working unchanged.
- `src/eval_harness/targets/provenance.py` — `EvidenceStore` Protocol (one call: `fetch`) + `MappingEvidenceStore` (ADR 0047). The seam for requirements-generation evidence retrieval: live adapters (Google Drive, Context7) sit behind this protocol while offline evaluations and synthetic corpora use the deterministic in-memory store. Verification is *not* a store method — `verify_provenance` re-fetches through `fetch` and compares hashes itself, so a store cannot certify bytes it has already drifted away from.
- `src/eval_harness/targets/testgen_agent.py` — registered `testgen_agent` pipeline (F-069, ADR 0048). Strip `inputs.suite` on a **deep copy**, then `run_generated_suite`. The registry name is **not** an ADR 0039 allowlist entry; ADR 0039 applies only to optional `generator_path`. Never allowlist `eval_harness`. Do not fold this into `targets/testgen.py` (size-budget).
- `src/eval_harness/replay/` — fixture replay of recorded `AgentTrajectory` envelopes (F-070, ADR 0049). Exact re-score and counterfactual observation swap are a `TargetRunner`, never a scorer (ADR 0046). JSONL archive confined by `DATA_ROOT`/`OUTPUT_ROOT`. The engine never reconstructs trajectories from Langfuse/Phoenix spans. ClickHouse is not a harness extra.
- `src/eval_harness/scorers/__init__.py` — `autoevals` bridges BrainTrust's `autoevals` scorer library (heuristic offline-safe; LLM/Embedding need a provider key). `src/eval_harness/datasets/__init__.py` — `braintrust` pulls a dataset via `init_dataset` (fail-fast when the SDK is absent).

Test the "SDK absent" path via `sys.modules` injection, not `@patch(...)` — see `feedback_agents_offline_optional_dep_testing` behaviour documented in existing tests. `@patch("phoenix.otel.register")` raises `ModuleNotFoundError` at patch time when the SDK isn't installed. The concrete idiom is `monkeypatch.setitem(sys.modules, "phoenix.otel", None)`, which forces the lazy import to `ImportError` even when the extra *is* installed (this venv installs all extras).
