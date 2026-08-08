# Claude Code ecosystem research — seven repos, and how they map onto this monorepo

Research date: **2026-08-08**. Star counts, release versions, and activity figures were
verified against the live GitHub API / npm registry on that date; they will drift.

## Scope and method

Source material: the seven repositories popularized by the Medium article
["7 GitHub Repos That Made Me Addicted to Building with Claude AI"](https://medium.com/@the_infinity/7-github-repos-that-made-me-addicted-to-building-with-claude-ai-6a2b148a4cad)
(@the_infinity, ~2026-08-07) — [zilliztech/claude-context](https://github.com/zilliztech/claude-context),
[modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers),
[rtk-ai/rtk](https://github.com/rtk-ai/rtk),
[jarrodwatts/claude-hud](https://github.com/jarrodwatts/claude-hud),
[hesreallyhim/awesome-claude-code](https://github.com/hesreallyhim/awesome-claude-code),
[thedotmack/claude-mem](https://github.com/thedotmack/claude-mem), and
[yamadashy/repomix](https://github.com/yamadashy/repomix).

Each repo was researched from its live README/docs/releases, GitHub API metadata, and
independent third-party coverage — not from the article alone. (The article body itself was
egress-blocked from this environment; its per-repo theses were reconstructed from search
snippets and are marked accordingly in the last section.)

Every incorporation idea is evaluated against this repo's standing doctrine:

- **Reversible adoption** ([docs/phoenix-spike.md](phoenix-spike.md)): SDK-optional,
  default-off, null-client test doubles, deletable in one commit.
- **No hard-coded values**
  ([ADR 0009](decisions/0009-tech-debt-audit-and-compat-surface.md)): env-var credentials,
  config-schema defaults.
- **Offline-deterministic test suite**: nothing network-dependent in the default pytest path.
- **Protected eval surfaces**: [`features.yaml`](../features.yaml), `scripts/validations/`,
  `.github/`, `tests/` require the labeled-approval flow (see
  [`AGENTS.md`](../AGENTS.md)) — several proposals below therefore *end* in an
  [OpenSpec](../openspec/README.md) package rather than a direct change.

Before implementing any item below, run the repo's own collision predictor —
`python skills/repo-invariant-review/scripts/check_invariants.py --repo . --base origin/main`
([repo-invariant-review](../skills/repo-invariant-review/SKILL.md)) — which predicts
protected-path, size-budget, airgap, and baseline failures before they reach CI.

## The landing zones (this repo's integration surfaces)

| Surface | Where | What can land there |
|---|---|---|
| [`claude-foundation`](../claude-foundation/README.md) plugin | `claude-foundation/.claude-plugin/plugin.json`, `hooks/hooks.json`, `agents/`, `skills/` | Bundled MCP servers (no `.mcp.json` exists today — net-new and cleanly reversible), new hooks, a statusline component, new skills |
| [Skills marketplace](../skills/README.md) | [`skills/marketplace.yaml`](../skills/marketplace.yaml) (+ `marketplace.schema.json`, `scripts/skill_marketplace.py validate`) | New vendored skills (name/version/path/description/compatibility entries) |
| Eval-harness registries | [`src/eval_harness/`](../src/eval_harness/README.md) datasets / scorers / judges / sinks | New pluggable components behind the established null-client seam |
| CI quality gates | `Makefile`, `scripts/quality-gate.sh`, feature validators | Deterministic budget/lint gates (changes touching protected paths go through OpenSpec + label) |
| Docs & governance | [`docs/decisions/`](decisions/README.md), [`openspec/`](../openspec/README.md) | ADRs and OpenSpec packages for anything above |

## Verdict summary

| Repo | What it is | Stars | License | Verdict |
|---|---|---|---|---|
| yamadashy/repomix | Deterministic repo→single-file packer, CLI + MCP + official Claude Code plugins | 27.7k | MIT | **Adopt now** — best doctrinal fit; CI-safe, offline, token-budget gate built in |
| modelcontextprotocol/servers | Official MCP reference servers (7 remain) | 89.4k | MIT/Apache-2.0 | **Adopt selectively** — bundle pinned Memory + Sequential Thinking default-off; use as style corpus for our own MCP server |
| hesreallyhim/awesome-claude-code | Curated ecosystem index, generated from a CSV registry | 51.9k | CC BY-NC-ND 4.0 | **Adopt the pattern + submit to it** — registry-generation ideas; the distribution channel for `claude-foundation` |
| thedotmack/claude-mem | Persistent memory: per-tool-call capture → LLM compression → re-injection | 90.1k | Apache-2.0 | **Adopt the data model, not the runtime** — typed observations + FTS5 + progressive disclosure on top of our session-logger |
| jarrodwatts/claude-hud | Statusline HUD ("htop for Claude Code"), zero hooks, zero network | 27.2k | MIT | **Recommend to devs; borrow the telemetry tap** — statusline/transcript parsing as harness metadata |
| zilliztech/claude-context | Semantic code-search MCP over Milvus + embeddings | 12.3k | MIT | **Default-off dev convenience only** — external infra + non-determinism; also a good system-under-test for the harness |
| rtk-ai/rtk | Rust CLI proxy compressing shell output 60–90% (claimed) | 75.3k | Apache-2.0 | **Measure first — do not adopt on reputation**: an independent benchmark found it *raised* session cost; dogfood the harness on the question |

---

## Repo-by-repo findings

### 1. zilliztech/claude-context — semantic code search MCP

**What it is.** An MCP server (plus core library and VS Code extension; TypeScript, Node 20+)
that indexes a codebase into Milvus and gives agents a `search_code` natural-language
retrieval tool. Hybrid BM25 + dense-vector search, AST-based chunking, Merkle-tree
incremental re-indexing. Zilliz's own evaluation claims ~40% token reduction at equivalent
retrieval quality.

**Integration mechanism.** Plain MCP registration, no plugin or hooks:

```bash
claude mcp add claude-context \
  -e OPENAI_API_KEY=... -e MILVUS_ADDRESS=... -e MILVUS_TOKEN=... \
  -- npx @zilliz/claude-context-mcp@latest
```

Four MCP tools: `index_codebase`, `search_code`, `clear_index`, `get_indexing_status`.
Config is fully env-var driven (`EMBEDDING_PROVIDER` = OpenAI default / VoyageAI / Gemini /
**Ollama** — the only keyless local path), with a global `~/.context/.env`.

**Health check.** MIT; 12.3k stars; created 2025-06; last push 2026-07-14; npm 0.1.15
(2026-06-22), pre-1.0, no GitHub releases. Known rough edges: snapshot corruption,
force-reindex issues, gRPC deadline errors against idle Zilliz clusters, BM25 weakness on
exact identifiers, per-machine index state. Requires running Milvus infrastructure
(Zilliz Cloud free tier or self-hosted) plus an embedding provider.

**Fit assessment.** The weakest doctrinal fit of the seven: always-on external infrastructure,
API keys, and non-deterministic retrieval results. But it is honest, env-driven, and MIT —
usable as an *opt-in developer convenience* and genuinely interesting as a
*system-under-test* for this repo's core competency.

**Incorporation plan.**

1. *(P3, default-off)* An MCP entry in `claude-foundation` gated behind env placeholders,
   version-pinned (never `@latest`), documented via ADR. `pre-tool-guard` should allowlist
   `search_code`/`get_indexing_status` and require approval for `index_codebase`/`clear_index`
   (writes to external infra). Keyless local profile: `EMBEDDING_PROVIDER=Ollama` +
   self-hosted Milvus, dev-machine only — never CI.
2. *(P2, high-signal)* A **retrieval-quality eval** in `langfuse-eval-harness`: a dataset of
   code-retrieval queries with gold-file labels over fixture repos, scorers for recall@k and
   token-cost-per-correct-retrieval, claude-context as the first system-under-test — behind
   a null Milvus/embedding double so the default suite stays offline.
3. *(P2)* A `semantic-search-discipline` skill in `skills/marketplace.yaml`: when to prefer
   `search_code` over Grep (concept queries vs exact identifiers — its documented BM25
   weakness), and a "verify every retrieved snippet with Read" rule. Inert without the MCP
   server; zero runtime cost.

### 2. modelcontextprotocol/servers — the official MCP reference servers

**What it is.** Anthropic's reference-implementation repo for MCP — deliberately *not* a
registry (discovery moved to registry.modelcontextprotocol.io). After the 2025 archive sweep
(13 servers moved to `servers-archived`), exactly **seven** reference servers remain as of
Aug 2026: Everything, Fetch, Filesystem, Git, **Memory** (knowledge-graph JSONL),
**Sequential Thinking**, and Time. TS servers ship as `@modelcontextprotocol/server-*` (npx);
Python ones as `mcp-server-*` (uvx).

**Integration mechanism.** Three routes, all relevant: `claude mcp add ... -- npx -y ...`;
a project-scoped `.mcp.json`; or **plugin-bundled** (`.mcp.json` at plugin root or an
`mcpServers` field in `plugin.json`) — the route that matters for `claude-foundation`.

**Health check.** 89.4k stars; ~4,150 commits; last push 2026-08-05. Dual-license transition
(existing MIT, new contributions Apache-2.0). Reference-quality by design, not
production-hardened. `npx -y`/`uvx` fetch latest-at-invocation unless pinned — a
supply-chain and determinism hazard to manage explicitly.

**Fit assessment.** Two distinct values for this repo: (a) Memory + Sequential Thinking are
the highest-trust "agent cognition" servers and slot straight into the plugin as default-off,
pinned, reversible config; (b) the repo is the canonical *style corpus* for writing our own
MCP server — the most strategic idea on this list.

**Incorporation plan.**

1. *(P1)* **An `eval-harness` MCP server**, modeled on `src/git`'s Python/FastMCP structure:
   tools `run_eval`, `list_datasets`, `get_scores`, `compare_runs`, so any Claude Code
   session can drive evals and read results without shelling out. New module + pinned `mcp`
   SDK as an optional extra; stdio transport makes an offline null-transport test double
   trivial — the same seam pattern as `phoenix_client`. This is the repo exporting its core
   competency to the agent ecosystem, not importing someone else's.
2. *(P2, default-off)* Bundle **Memory + Sequential Thinking** in a new
   `claude-foundation/.mcp.json` with pinned versions and `MEMORY_FILE_PATH` env-directed to
   a gitignored `.claude/memory/`. Reversible by deleting one config block; document that
   npx implies network at session start (keep out of any test path).
3. *(P2)* An **MCP-hygiene validator** in the quality-gate family: lint every `.mcp.json` in
   the repo — versions pinned, commands on an npx/uvx allowlist, denylist of the 13 archived
   server packages (unmaintained upstream). Near-zero cost; lands via the OpenSpec flow since
   validators are protected paths.
4. *(P3)* Scoped **Filesystem** server entries for the `explorer`/`test-runner` subagents
   (allowed-roots restricted per package) to turn "least-privilege subagents" from a prompt
   convention into an enforced boundary — watch for double-denial confusion with
   `pre-tool-guard`.

### 3. rtk-ai/rtk — token-compression CLI proxy

**What it is.** "Rust Token Killer": a single-binary CLI proxy that rewrites shell commands
(`git status` → `rtk git status`) via a **PreToolUse hook** and compresses their output
before the agent reads it (filtering, grouping, truncation, dedup; 100+ commands incl.
pytest/ruff/cargo). Claims 60–90% token reduction; `rtk gain` dashboards the savings; a tee
system preserves raw output on failure. Integration: `rtk init -g` (hook + RTK.md),
`rtk init -g --uninstall` to remove; excludes configurable in `~/.config/rtk/config.toml`.

**Health check.** Apache-2.0; 75.3k stars in ~6.5 months (created 2026-01-22 — hype-cycle
caveats apply); near-weekly releases (v0.45.0, 2026-08-07); 1,903 open issues. Token math is
bytes/4 — rtk ships no tokenizer (its own README says absolute numbers are approximate).

**The critical finding.** An independent controlled benchmark
([JetBrains, 2026-07-20](https://blog.jetbrains.com/ai/2026/07/rtk-claude-code-token-savings/),
80 paired trials) found rtk **raised** Claude Code session cost: median **+7.6% per task**
(p=0.004), +13.8% turns, +14.3% cache reads — while `rtk gain` self-reported 96.2M tokens
"saved" on the same trials. Causes: `rtk gain` measures compression against a counterfactual,
not the bill; Claude Code's built-in Read/Grep/Glob bypass the Bash hook entirely; compressed
output degrades agent effectiveness, adding turns that swamp per-command savings.

**Fit assessment.** This is precisely the kind of claim `langfuse-eval-harness` exists to
adjudicate. Global adoption on reputation would be malpractice by this repo's own standards;
the JetBrains result is one workload profile, not a universal verdict — so measure here,
on this repo's pytest/ruff-heavy workloads.

**Incorporation plan.**

1. *(P1 — the flagship dogfooding move)* A **paired-trial scenario in the `model-bench`
   skill**: rtk-on vs rtk-off arms (`rtk init -g --auto-patch` / `--uninstall`), scored by a
   harness scorer that reads *actual* input tokens from Langfuse traces, never `rtk gain`'s
   bytes/4 estimate. Reproduces the JetBrains methodology on our own workloads and produces
   a defensible adopt/reject ADR. ~80 paired trials for significance.
2. *(P2, technique-not-tool)* A **pure-Python output compactor** in the harness pipeline
   (dedup repeated log lines with counts, group failures by type, keep first+last N of
   tracebacks) applied before eval artifacts reach LLM judges, with before/after token counts
   traced. Captures the sound part of rtk's idea with zero external dependency and full
   determinism; verify score-neutrality through `agent-core` calibration before enabling.
3. *(P3, only if #1 shows net savings)* Default-off rtk hook entry in `claude-foundation`
   gated on an env flag. Named risk: **hook-ordering with `pre-tool-guard`** — the guard must
   see the rewritten command (or consistently run before rewriting), and rtk's weekly-changing
   rewrite behavior is a moving target for a deterministic gate. Tee files also write raw
   command output to `~/.local/share/rtk/tee/` (a secrets-handling consideration).

### 4. jarrodwatts/claude-hud — the statusline HUD

**What it is.** "htop for Claude Code": a statusline plugin rendering context-window %,
usage-window burn, active tools, running subagents, and todo progress under the input box.
Architecturally notable for what it *doesn't* do: **zero lifecycle hooks, zero storage, zero
network** — a stateless subprocess fed stdin JSON by Claude Code's native statusline API,
plus read-only parsing of the session transcript JSONL. MIT; 27.2k stars; v0.7.0 (2026-08-07);
very active. Install: `/plugin marketplace add jarrodwatts/claude-hud` →
`/plugin install claude-hud` → `/claude-hud:setup`. Kill switch `CLAUDE_HUD_DISABLE=1`.

**Limitations.** Usage bars require a subscription account (not API-key); the statusline slot
is a global singleton in settings.json (collides with other statusline tools); depends on the
undocumented transcript JSONL format.

**Fit assessment.** As a developer tool: simply recommend it — vendoring adds no value and
its release cadence is fast. The durable value to this repo is its two *transport contracts*:
the statusline stdin JSON (real token counts, not estimates) and the transcript JSONL, both
of which are telemetry taps the harness can consume.

**Incorporation plan.**

1. *(P1, docs-only)* Recommend claude-hud (pinned version) in `claude-foundation`'s README as
   the observability companion; note the statusline-singleton caveat.
2. *(P2)* **Session-metrics enrichment for the `session-logger` hook**: adopt claude-hud's
   transcript-parsing pattern to derive per-session metrics (tool-call counts by type,
   subagent spawns, context % per turn) and emit them through the harness's Langfuse sink as
   trace metadata — correlating context pressure with eval scores and regression-gate
   outcomes. Feature-flagged, with fixture-based offline tests (the transcript format is
   undocumented and will drift).
3. *(P3)* A repo-specific statusline component in `claude-foundation` surfacing quality-gate /
   behavioral-regression state during sessions. Real cost: it's a JS/Bun artifact in a Python
   monorepo competing for a singleton slot — only worth it if #2 proves the signal useful,
   and it should optionally *wrap* an existing statusline command rather than replace it.
4. *(P3)* Context-pressure telemetry as an input to `agent-core` calibrated policies
   ("compact now / stop spawning subagents") — null-objected in headless/CI runs where the
   statusline signal doesn't exist.

### 5. hesreallyhim/awesome-claude-code — the ecosystem index

**What it is.** The curated index of the Claude Code ecosystem (51.9k stars; commits land
daily). Mechanically interesting: the README is **generated** from a CSV single source of
truth + `config.yaml` via idempotent Python tooling (`make generate`, byte-identical re-runs,
fails closed on unknown categories). Submissions are **issue-form-only** (PRs from outsiders
are impossible by policy); a bot validates each submission, auto-discovers licenses, and
enforces ground rules (≥14 days old + active, or 100+ stars). License is CC BY-NC-ND 4.0 —
curation is browsable but not forkable into derivative lists.

**Resources it indexes that matter to this repo:** `anthropics/skills` (the SKILL.md format
we vendor), `anthropics/claude-plugins-official`, `anthropics/claude-code-action` +
`claude-code-security-review` (CI-native review actions), `obra/superpowers` (the closest
peer to `foundation:plan`/`code-review`/`test-first`), `agent-sh/agnix` (a linter/LSP for
CLAUDE.md/AGENTS.md/SKILL.md/hooks/MCP configs), `Zandereins/schliff` (deterministic
8-dimension scorer for instruction files, anti-gaming, zero deps), `wei18/Upkeep`
(docs/spec-drift audit — a conceptual sibling of `architecture-drift-guard`), and
`diet103/claude-code-infrastructure-showcase` (hook-driven automatic skill activation).

**Incorporation plan.**

1. *(P1)* **Submit `claude-foundation` to the list** via the issue form (it clears the
   ≥14-days-active rule; category: Skills or Agent Orchestration; one-line factual
   description, one submission at a time). On acceptance, add the awesome.re "Mentioned in"
   badge. Highest-leverage distribution channel found in this research.
2. *(P2)* **Registry-generation pattern for `skills/marketplace.yaml`**: generate the
   `skills/README.md` catalog from the registry idempotently with a byte-identical CI
   assertion (exactly the shape of the existing `matrix-coverage.md` freshness gate), and
   add per-skill freshness badges. Their issue-form + bot-validator pipeline is the model
   for accepting third-party skill submissions without opening the registry to PRs.
3. *(P2)* **Evaluate `agnix` and `schliff` as skill-quality gates**: machine-lint and
   machine-score every SKILL.md in `skills/` and `claude-foundation/skills/` before
   marketplace registration — a stronger companion to the structural `validate_skill.py`.
   Pin versions; run them in the skills CI lane first as non-blocking, gate later.
4. *(P3)* Study `diet103`'s hook-driven **automatic skill activation** pattern for
   `claude-foundation`'s hooks — auto-selecting the right foundation skill from context
   rather than relying on the user to invoke it.

### 6. thedotmack/claude-mem — persistent memory

**What it is.** The largest-starred Claude Code plugin (90.1k; Apache-2.0; v13.14.0
released the day of this research). Five lifecycle hooks capture every tool call
(PostToolUse → non-blocking ~8ms HTTP POST), a resident Bun/Express worker compresses
outputs via the Claude Agent SDK into ~500-token **typed observations** (9 types: decision,
bugfix, feature, refactor, discovery, …, sensitive), stored local-first in SQLite+FTS5 +
Chroma vectors, and re-injected at SessionStart (matcher `startup|clear|compact`). Retrieval
is a deliberate 3-layer progressive disclosure: `search` (~50–100 tokens/result) → `timeline`
→ `get_observations` (~500–1,000 tokens/result). Install: `npx claude-mem install`.

**Costs and risks.** Every tool call triggers an LLM compression call (subscription quota or
API spend; Haiku-class default mitigates). Records everything by default — privacy opt-outs
are `<private>` tags and the "sensitive" type; a commercial cloud tier (CMEM Pro) is
increasingly promoted. Operationally heavy: Bun worker must stay up (documented restart-storm
and port-race incidents), plus uv/Python/Chroma. Injected memories consume context budget and
are a prompt-injection-shaped surface.

**Fit assessment.** The runtime is the opposite of this repo's doctrine (always-on worker,
three runtimes, per-call LLM spend). The **data model and retrieval contract are excellent**
and worth adopting on top of infrastructure this repo already owns: `session-logger` already
produces the JSONL audit log that claude-mem's capture layer exists to create.

**Incorporation plan.**

1. *(P1)* **Memory distillation as a default-off extension of `session-logger`**: an
   SDK-optional post-processing stage (batched at SessionEnd, not per-tool-call — capping
   cost) that distills the existing JSONL log into claude-mem-style typed observations in a
   local SQLite+FTS5 index. Null-compressor double keeps the suite offline; golden-file
   tests pin the taxonomy.
2. *(P2)* **A compression-fidelity judge in the harness**: score (raw tool output →
   observation) pairs for factual retention, hallucination, and token-budget compliance —
   memory quality as a measured, gated property. Nobody in this ecosystem evaluates memory
   compression quality; this is a differentiator that directly reuses existing judge
   plumbing and fits `agent-core`'s calibration mandate.
3. *(P2)* **claude-mem archives as an eval dataset source**: a pluggable dataset adapter
   reading `~/.claude-mem/claude-mem.db` (pin a schema version; validate on load; filter
   "sensitive" observations before any upload) to convert real agent history into retrieval
   and compression eval corpora, complementing `flow-corpus`.
4. *(P2)* **Golden-file regression gate for context injection**: from a fixed SQLite
   fixture, assert the SessionStart-injected context block byte-for-byte — guarding the
   highest-blast-radius prompt-injection surface a memory system has. Pure-offline; fits the
   behavioral-regression gate's existing shape.
5. *(P3)* A `mem-search`-style progressive-disclosure skill over the distilled index,
   copying the 3-layer token-budget contract.

### 7. yamadashy/repomix — deterministic repository packing

**What it is.** Packs a repository (local or remote) into one AI-friendly file
(XML default / Markdown / JSON / plain), git-aware, with local tiktoken token accounting —
zero external services. Key capabilities: `--compress` (Tree-sitter signature extraction,
~70% claimed token cut), **`--token-budget N` (non-zero exit when exceeded — built for CI)**,
`--token-count-tree` (per-file token heat map), Secretlint scanning **on by default**,
`--remote owner/repo --remote-branch <sha>` pinned remote snapshots, and
`--skill-generate` (mints Agent Skills-format codebase-reference skills, monorepo-aware).
Ships its own Claude Code plugin marketplace in-repo (`repomix-mcp`, `repomix-commands`,
`repomix-explorer`) and an MCP mode (`repomix --mcp`) with a `--sandbox` flag (v1.18.0).

**Health check.** MIT; 27.7k stars; created 2024-07; pushed the day of this research;
v1.18.0 (2026-08-04); monthly-or-faster cadence; 4,395 commits. Limitations: lexical (no
semantic retrieval — the explorer pattern is pack → Grep/Read); very large monorepos can
exceed context even compressed.

**Fit assessment.** The best doctrinal fit of the seven: deterministic, offline,
dependency-free, secret-scanned, CI-native. Complementary to claude-context, not competing
(stateless packing vs stateful retrieval).

**Incorporation plan.**

1. *(P1)* **CI token-budget gate**: per-package
   `npx repomix@<pinned> --compress --style xml --token-budget <N> --token-count-encoding o200k_base`,
   with `--token-count-tree` emitted as a job artifact showing token hotspots. Turns context
   bloat into a measurable, gated regression — the same philosophy as the
   behavioral-regression gate, fully deterministic. Budgets need per-package calibration;
   cache the pinned npx fetch.
2. *(P1)* **A `repo-pack` skill in `skills/marketplace.yaml`** wrapping the CLI (pack with
   `--compress`, then Grep/Read the output — the official explorer agent's own workflow),
   giving the `explorer` subagent token-efficient comprehension of *external* dependencies
   with zero new infrastructure and no MCP surface. Route packs to a gitignored scratch dir.
3. *(P2)* **Fixture/corpus packing for the harness**: repomix as a dataset-prep adapter
   (`--style json`) for code-review/judge scenarios, and pinned-commit remote snapshots into
   `flow-corpus` — reproducible, secret-scanned corpora whose exact token counts become
   dataset metadata on Langfuse traces. Pin the JSON schema to a repomix version; store pack
   manifests rather than large packs where possible.
4. *(P3)* **`--skill-generate` + drift guard**: CI regenerates per-package
   codebase-reference skills and diffs against the committed ones, à la
   `architecture-drift-guard`. The feature is young (v1.14+); pin the version and treat
   regeneration as an explicit change.

### The Medium article itself

The article is a competent popularization, not a source of technical detail: its thesis is
that these tools are "force multipliers" forming a layered stack — discovery
(awesome-claude-code), context ingest (repomix, claude-context), external actions (MCP
servers), efficiency (rtk), memory (claude-mem), observability (claude-hud). Two research
notes: (a) the article body was not directly fetchable from this environment (Medium and its
mirrors are egress-blocked); per-repo claims above were reconstructed from search snippets
and verified against primary sources instead. (b) Its efficiency framing of rtk repeats the
60–90% headline without the JetBrains counter-evidence — a useful reminder that this repo's
adoption decisions should come from measurements, not listicles.

The layered mental model is genuinely useful, though — and this monorepo already formalizes
most layers (Langfuse tracing ↔ observability; eval-corpus-forge/flow-corpus ↔ context
corpora; claude-foundation hooks ↔ the same PreToolUse mechanism rtk uses). The gaps the
article's stack exposes here are **memory** (no distillation/retrieval over session logs)
and **context-budget discipline** (nothing measures package context footprint today) —
which is exactly where the P1 items below land.

---

## Prioritized roadmap

**P1 — do first (offline-safe, high leverage, no protected-path friction):**

1. Repomix **CI token-budget gate** + `repo-pack` skill (repomix #1–2), registered in
   [`skills/marketplace.yaml`](../skills/marketplace.yaml).
2. **`eval-harness` MCP server** modeled on the reference servers (servers #1), behind the
   [phoenix-style SDK-optional seam](phoenix-spike.md).
3. **rtk paired-trial benchmark** via [`model-bench`](../skills/model-bench/SKILL.md) +
   Langfuse-measured tokens (rtk #1) — publish the adopt/reject ADR either way.
4. **Memory distillation** extension of the
   [`session-logger`](../claude-foundation/hooks/session_logger.py) hook (claude-mem #1).
5. **Submit [`claude-foundation`](../claude-foundation/README.md) to awesome-claude-code**
   (awesome #1) — docs-only, plus a pinned claude-hud recommendation in the plugin README
   (hud #1).

**P2 — pattern adoption and measurement (some need OpenSpec packages):**
compression-fidelity judge and claude-mem dataset adapter (claude-mem #2–4); session-metrics
telemetry into Langfuse (hud #2); retrieval-quality eval + search-discipline skill
(claude-context #2–3); marketplace registry generation + agnix/schliff skill gates
(awesome #2–3); MCP-hygiene validator (servers #3); pure-Python output compactor (rtk #2);
harness fixture packing (repomix #3).

**P3 — conditional / deferred:** bundled Memory + Sequential Thinking and scoped Filesystem
servers (servers #2, #4); default-off claude-context MCP entry (claude-context #1); rtk hook
(only if the P1 benchmark says yes); repo-specific statusline + agent-core context-pressure
policies (hud #3–4); `--skill-generate` drift guard (repomix #4); hook-driven skill
activation study (awesome #4).

## Cross-cutting risks (apply to every adoption above)

- **Supply chain / determinism:** every `npx`/`uvx` invocation must be version-pinned;
  `@latest` is an unreviewed dependency bump on every session start. The proposed MCP-hygiene
  validator generalizes this.
- **Hook interactions:** anything that rewrites or observes tool calls (rtk, memory capture)
  must have a defined ordering relative to `pre-tool-guard`, or the guard's allow/deny
  decisions silently desync from what actually executes.
- **Prompt-injection surface:** context re-injection (claude-mem-style) and retrieved
  snippets (claude-context) put unreviewed content into every session prompt; the golden-file
  injection gate (claude-mem #4) is the control.
- **Secrets:** session logs, tee files, packed repos, and memory DBs all accumulate raw tool
  output. Repomix's default Secretlint scan is the model; any distillation/packing pipeline
  here needs the same fail-closed posture before anything leaves the machine.
- **Vendor gravity:** claude-context (Zilliz Cloud) and claude-mem (CMEM Pro) are open-source
  on-ramps to commercial services. Local-first profiles (Ollama/self-hosted Milvus; local
  SQLite) keep the exits open.

## Sources

Primary: each repo's README/docs/releases and GitHub API metadata (2026-08-08); npm registry
(`repomix` 1.18.0, `@zilliz/claude-context-mcp` 0.1.15). Secondary:
[JetBrains rtk benchmark](https://blog.jetbrains.com/ai/2026/07/rtk-claude-code-token-savings/),
[TechTimes coverage](https://www.techtimes.com/articles/321223/20260721/rtk-raises-claude-code-costs-low-effort-jetbrains-benchmark-debunks-6090-claim.htm),
[Developers Digest on claude-context](https://www.developersdigest.tech/blog/github-trending-claude-context-2026-04-28),
[apidog claude-mem guide](https://apidog.com/blog/how-to-use-claude-mem/),
[statusline comparison](https://yigitkonur.com/research/claude-code-statuslines-compared),
[Repomix Claude Code plugins guide](https://repomix.com/guide/claude-code-plugins),
and the [Medium article](https://medium.com/@the_infinity/7-github-repos-that-made-me-addicted-to-building-with-claude-ai-6a2b148a4cad)
(via search snippets; direct fetch egress-blocked).
