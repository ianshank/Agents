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
| postgres | 16-alpine | `sha256:44c4ee9810eff91f7eab4d822642e01115b1a9eccce4bcbdde7604752d68eac6` | 2026-08-16 | registry manifest API (see note below) |
| redis | 7-alpine | `sha256:e7723ff73d963f5cc6d9c4643ea3d989527a402a319239054e9472a7fb9219a2` | 2026-08-16 | registry manifest API (see note below) |
| clickhouse/clickhouse-server | 24.8-alpine | `sha256:b002e56ed5c16e224c312527f6fcba7e77216fec5d7a88a7828f59efc614feb5` | 2026-08-16 | registry manifest API (see note below) |
| minio/minio | RELEASE.2024-09-13T20-26-02Z | `sha256:cd04ea408e185cb50076ea1c3988d444119b19aaae15aab45387ccf14b2a2f86` | 2026-08-16 | registry manifest API (see note below) |
| langfuse/langfuse | 3 | `sha256:60a668b1dd06e2d9a034ba8b2ed5e84303e66c6202d76b288020059a755fd037` | 2026-08-16 | registry manifest API (see note below) |
| langfuse/langfuse-worker | 3 | `sha256:138a5b510cd76262a2abb02af1ddc563105013fdc9a62e63ccce526140ad05ba` | 2026-08-16 | registry manifest API (see note below) |
| mysql | 8.4 | `sha256:b3b90af2a6552ae30c266fdb7d5dd55f3afb72404bb78d37fe8a23eb857fd3fb` | 2026-08-16 | registry manifest API (see note below) |
| ghcr.io/comet-ml/opik/opik-backend | 1.7.26 | `sha256:3f8ff690871daccf181346347f1fe429b301a6b187bce829d5cc845349c81ea0` | 2026-08-16 | registry manifest API (see note below) |
| ghcr.io/comet-ml/opik/opik-python-backend | 1.7.26 | `sha256:35374fc93b46a1f7c0633b6bde3c045cef91ce39985226e1832c1a51977c7dd9` | 2026-08-16 | registry manifest API (see note below) |
| ghcr.io/comet-ml/opik/opik-frontend | 1.7.26 | `sha256:1ba821742dd21d50d22f9cfe80bb9ad3fee2f6dbfa84c849c6055a3a939d7f33` | 2026-08-16 | registry manifest API (see note below) |
| ghcr.io/comet-ml/opik/opik-guardrails-backend | 1.7.26 | `sha256:8a47859fed49470071ba1f2133212a403d4a0272f1b196626cad7c5d3d4523d4` | 2026-08-16 | registry manifest API (see note below) |
| ollama/ollama | 0.9.6 | `sha256:f478761c18fea69b1624e095bce0f8aab06825d09ccabcd0f88828db0df185ce` | 2026-08-16 | registry manifest API (see note below) |
| python (prober base) | 3.11-slim | `sha256:a630a63cdb314e2d138a2fca3e375e319e8568346ffafac5b980f888630ac4f1` | 2026-08-16 | registry manifest API (see note below) |
| coredns/coredns (airgap DNS witness) | 1.12.1 | `sha256:e8c262566636e6bc340ece6473b0eed193cad045384401529721ddbe6463d31c` | 2026-08-16 | registry manifest API (see note below) |

The judge model (`${BV_JUDGE_MODEL:-llama3.2:3b}`) is pulled by tag into the named
volume at deploy time; its digest is recorded in `effort_metrics.json` at that moment.
