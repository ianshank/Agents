# Golden corpus (human labels)

**Current size: 0 items.** Phase 7 of eval-evidence-integrity cannot complete
without real human labels. This directory is the contract for how those labels
land; it is not a padded JSONL.

Do **not** commit synthetic rows with `provenance=human`.
`CorpusProvenanceConfig` treats unknown provenance as not-human, and
`require_human_corpus` refuses synthetic tokens. A gate that underwrites itself
with invented labels is worse than no gate.

## Schema (additive; no `SCHEMA_VERSION` bump)

Each line is a `GoldenItem` JSON object (`agent_core.golden.GoldenSet`):

```json
{"item_id": "…", "text": "…", "label": 0, "domain": "default", "source": "", "meta": {"provenance": "human"}}
```

`meta.provenance` must be `human` for every row that may underwrite a judge-backed
gate. `synthetic` is allowed in fixtures and tests only, never as activation
evidence.

## Floor

`CorpusProvenanceConfig.min_items` defaults to 50. Check a file with:

```bash
python -m agent_core.corpus_provenance --jsonl path/to/golden.jsonl
```

Pairwise annotator agreement:

```python
from agent_core.labeling_protocol import agreement_report
report = agreement_report(annotator_a, annotator_b)  # 0/1 sequences
assert report.may_accept
```

Adjudication (escalate on tie) is `adjudicate([0, 1, …])`.

## How labels get here

Two annotators, independent, then `adjudicate`. Protocol:
[runbooks/labeling-protocol.md](../runbooks/labeling-protocol.md).
Leadership record: [plans/vp-strategic-deep-dive/DECISIONS.md](../plans/vp-strategic-deep-dive/DECISIONS.md).
