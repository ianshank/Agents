# Labeling protocol (golden set and judge baselines)

The protocol is **config**, not a wiki page that can drift from the code.
Annotators follow this document; floors live on
`agent_core.labeling_protocol.LabelingProtocolConfig`.

## Defaults (retune the dataclass, not call sites)

| Field | Default | Meaning |
|---|---|---|
| `n_annotators` | 2 | A single annotator cannot produce Cohen's κ |
| `min_kappa` | 0.60 | Landis–Koch "substantial" |
| `min_percent_agreement` | 0.80 | Secondary floor |
| `min_pairs` | 50 | Matches `CorpusProvenanceConfig.min_items` |
| `tie_policy` | `escalate` | Ties do not silently pick a side |

`adjudicate(labels)` is majority vote on `{0, 1}`. A tie returns
`Adjudication(label=None, reason="tie:escalate")` (or `tie:require_third`).
There is no majority-of-one.

`agreement_report(r1, r2)` reuses `agent_core.golden.cohen_kappa` and
`percent_agreement` — it does not reimplement them.

## Provenance

Every `GoldenItem` that may underwrite a gate must carry
`meta[CorpusProvenanceConfig.meta_key] = CorpusProvenanceConfig.human_value`
(`provenance=human`). Synthetic or missing provenance fails
`require_human_corpus`. See [golden-corpus/README.md](../golden-corpus/README.md).

## Judge baselines

A `JudgeCalibrationReport` that `may_gate` on probes still cannot authorise a
blocking gate without a human corpus at these floors.
`python -m agent_core.judge_baseline --report <json> --corpus <jsonl>` composes
`may_gate` + kappa + `n_codeterminate` + provenance. `--allow-synthetic-corpus`
is debug-only.

## What this document will not do

It will not supply labels. Inventing 50 rows to "close" Phase 7 would underwrite
gates with fiction. The empty corpus is the honest state.
