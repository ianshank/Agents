# Image digest provenance (spec R11)

Every compose image must be pinned `tag@sha256:<digest>` before `make deploy` will run —
`deploy.py` refuses unpinned refs, including the `TODO_PIN` markers below. This file is
the audit trail: when a digest was resolved, with what command, by whom.

## How to pin

Run where the registries (docker.io, ghcr.io) are reachable:

```
make pin-digests
```

That resolves each `TODO_PIN` via `docker manifest inspect --verbose <ref>` (pinning the
manifest-list digest, so multi-arch stays intact), rewrites the compose `image:` lines in
place, and you commit the result together with the updated table below. Re-pinning to
newer tags is a deliberate, reviewed PR — never an implicit side effect of deploying.

## Current pins

| Image | Tag | Digest | Resolved (UTC) | Command |
|---|---|---|---|---|
| postgres | 16-alpine | TODO_PIN | — | — |
| redis | 7-alpine | TODO_PIN | — | — |
| clickhouse/clickhouse-server | 24.8-alpine | TODO_PIN | — | — |
| minio/minio | RELEASE.2024-09-13T20-26-02Z | TODO_PIN | — | — |
| langfuse/langfuse | 3 | TODO_PIN | — | — |
| langfuse/langfuse-worker | 3 | TODO_PIN | — | — |
| mysql | 8.4 | TODO_PIN | — | — |
| ghcr.io/comet-ml/opik/opik-backend | 1.7.26 | TODO_PIN | — | — |
| ghcr.io/comet-ml/opik/opik-python-backend | 1.7.26 | TODO_PIN | — | — |
| ghcr.io/comet-ml/opik/opik-frontend | 1.7.26 | TODO_PIN | — | — |
| ollama/ollama | 0.9.6 | TODO_PIN | — | — |
| python (prober base) | 3.11-slim | TODO_PIN | — | — |

The judge model (`${BV_JUDGE_MODEL:-llama3.2:3b}`) is pulled by tag into the named
volume at deploy time; its digest is recorded in `effort_metrics.json` at that moment.
