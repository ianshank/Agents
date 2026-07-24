# claude-foundation

> **STAGING NOTICE:** this component currently lives **in-tree** inside the
> `ianshank/Agents` monorepo at `claude-foundation/`. Extraction to its own
> repository (`ianshank/claude-foundation`) is planned but not yet done — see
> [ADR 0017](../docs/decisions/0017-claude-foundation-reconciliation.md). Until
> then, treat **this directory** (`claude-foundation/`) as the repository root:
> run the commands below from here (`cd claude-foundation`), and read the
> `ianshank/claude-foundation` marketplace references as the post-extraction
> target.

`claude-foundation` is a versioned Claude Code plugin (plugin name: **`foundation`**)
plus a self-hosted marketplace, packaging the reusable generic layer of an agentic
workflow: constraint-programming planning, code review, test-first enforcement, and C4
documentation skills; least-privilege explorer and test-runner subagents; and
deterministic lifecycle hook guards. Components are namespaced `foundation:*`, carry no
hardcoded values (all configuration is via environment variables), and ship with a full
validation and eval suite. Consumer repositories install it via the marketplace and pin
a semver tag — the single-source-of-truth alternative to copy-pasting agent config
across repos.

## Install

Add this repository as a marketplace, then install the plugin from it:

```bash
claude plugin marketplace add ianshank/claude-foundation   # or a local path to this repo
claude plugin install foundation@claude-foundation
```

To pin a specific version, point your marketplace entry's `source` at a semver tag via
its `ref` (or `sha`) field. See [Versioning contract](#versioning-contract).

### Local testing (no install)

Load the plugin for a single session directly from a checkout:

```bash
claude --plugin-dir .
```

### Validate the plugin structure

```bash
claude plugin validate .
```

## Components

| Type | Name | Purpose |
|---|---|---|
| Skill | `foundation:plan` | Instantiates the constraint-programming planning template for a new task |
| Skill | `foundation:code-review` | Security + quality review checklist, runs in a forked subagent |
| Skill | `foundation:test-first` | Enforces a write-tests-before-implementation workflow |
| Skill | `foundation:c4-docs` | Generates/updates C4 Mermaid diagrams for the host repo |
| Subagent | `explorer` | Read-only codebase scanner; cheap model alias; Read/Grep only |
| Subagent | `test-runner` | Runs the verification loop in isolation, returns a summary |
| Hook | `pre-tool-guard` | PreToolUse: blocks `.env` reads and denied-glob writes — **fails closed** |
| Hook | `post-edit-verify` | PostToolUse: verifies touched files — **fails open**, findings as context |
| Hook | `session-logger` | Structured JSONL audit log of tool calls when enabled |
| MCP | `.mcp.json.example` | MCP server template with env-var placeholders; no live servers |

Every skill ships with `evals/evals.json` (skill-creator format, ≥3 cases); see
[ADR 0003](docs/adr/0003-eval-integration-and-stdlib-logging.md).

## Configuration

All hook behavior is controlled by environment variables — never by literals in the
plugin:

| Variable | Effect |
|---|---|
| `CLAUDE_FOUNDATION_LOG_DIR` | When set, every hook emits structured JSONL logs into this directory. Unset = no log files. |
| `CLAUDE_FOUNDATION_GUARD_DENY_GLOBS` | Comma-separated list of extra deny globs for `pre-tool-guard`, added to its built-in rules (e.g. `secrets/**,*.pem`). |
| `CLAUDE_FOUNDATION_VERIFY_CMD` | Command template run by `post-edit-verify` against each edited file; `{file}` is replaced with the file path (e.g. `ruff check {file}`). Unset = verification skipped. |

## Development

```bash
pip install -e ".[dev]"

pytest                                # unit tests (hooks, validator, eval gate)
ruff check . && ruff format --check . # lint + formatting
mypy tools                            # strict type checking
python -m foundation_tools.validate   # frontmatter/manifest schema validation
python -m foundation_tools.scan       # no-hardcode scanner (allowlist policy)
claude plugin validate .              # official structure checker
```

Behavioral skill evals are release-blocking, not merge-blocking; they run via
`python -m foundation_tools.eval_gate` before a version tag is cut.

## Versioning contract

- Releases follow **semver** and are cut as git tags.
- **Component names are append-only within a major version**: no released skill,
  subagent, or hook name is renamed or removed without a major bump.
- Consumers should **pin** a release in their marketplace entry via the source's
  `ref` (tag) or `sha` field; upgrades are then deliberate, reviewable diffs.

See [CHANGELOG.md](CHANGELOG.md), the ADRs under [docs/adr/](docs/adr/), and
[docs/architecture.md](docs/architecture.md).
