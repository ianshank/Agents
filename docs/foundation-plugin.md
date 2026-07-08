# Consuming the `foundation` plugin (M7 dogfood)

This repo consumes the **generic** Claude Code layer from the extracted
[`ianshank/claude-foundation`](https://github.com/ianshank/claude-foundation) plugin, pinned to a
released tag — it does **not** vendor it. See [ADR 0017](decisions/0017-claude-foundation-reconciliation.md)
(reconciliation) and [ADR 0021](decisions/0021-claude-foundation-extraction.md) (extraction).

## Routing rule (what lives where)

- **Foundation (the plugin) supplies the generic layer:** skills `foundation:plan`,
  `foundation:code-review`, `foundation:test-first`, `foundation:c4-docs`; the `explorer` /
  `test-runner` subagents; and the lifecycle hook guards.
- **This repo keeps its 4 domain skills** unchanged in `skills/` (`openai-judge`,
  `architecture-drift-guard`, `eval-corpus-forge`, `model-bench`) — application code with their own
  95% coverage gates and drift-guard CI (ADR 0009). They are never migrated into the plugin, and the
  plugin's generic skills are never duplicated into `skills/`.

## Configuration

[`.claude/settings.json`](../.claude/settings.json) registers the marketplace pinned to `v1.0.0`
via the source `ref` and enables the plugin:

```json
{
  "extraKnownMarketplaces": {
    "claude-foundation": {
      "source": { "source": "github", "repo": "ianshank/claude-foundation", "ref": "v1.0.0" }
    }
  },
  "enabledPlugins": { "foundation@claude-foundation": true }
}
```

The equivalent one-time interactive setup is:

```
/plugin marketplace add ianshank/claude-foundation
/plugin install foundation@claude-foundation
```

## Notes

- **The plugin repo is private.** Consumers need read access; the pinned `ref` (`v1.0.0`) is bumped
  deliberately when adopting a new foundation release.
- **Config-only, per ADR 0017:** consuming the plugin adds no Python, no CI job, and no change under
  `skills/`, so it stays compatible with the protected-path guard and ledger auditing.
- The pre-extraction staging tree (`claude-foundation/`) and its inert root workflow were removed in
  the same PR that added this config (single revert point); `scripts/validations/F_039.py` guards
  the post-extraction state.
