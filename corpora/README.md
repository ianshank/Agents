# `corpora/` — versioned evaluation corpora loaded by the harness

Frozen, generated datasets that `eval_harness` loads through its shipped dataset
components. Each corpus lives under `corpora/<name>/<version>/` with a `manifest.json`
carrying its schema version, generator seed, and a content hash per item.

| Corpus | Generator | Loaded by |
|---|---|---|
| [`testgen/v1/`](testgen/v1/) | [`scripts/gen_testgen_corpus.py`](../scripts/gen_testgen_corpus.py) | [`config/testgen_eval.yaml`](../config/testgen_eval.yaml) via the `jsonl` dataset |
| [`rca/v1/`](rca/v1/) | [`scripts/gen_rca_corpus.py`](../scripts/gen_rca_corpus.py) | [`config/rca_eval.yaml`](../config/rca_eval.yaml) via the `jsonl` dataset |
| [`requirements/v1/`](requirements/v1/) | [`scripts/gen_requirements_corpus.py`](../scripts/gen_requirements_corpus.py) | [`config/requirements_eval.yaml`](../config/requirements_eval.yaml) via the `jsonl` dataset |

## What belongs here

Data that the **harness** loads: generated, reproducible, and verifiable against its own
manifest. `make corpus-check` (or each generator's `--check`) regenerates a corpus and
fails if the committed bytes differ, so a hand-edited item is caught rather than trusted.

Nothing host-specific, and nothing scraped from an internal system. A corpus of real
internal source would run at CHARTER §4 invariant 7 — *"Nothing host-specific is
committed"* — and would need that invariant relaxed under §6 as a §3 Ratified Amendment.
Generation avoids the question entirely, and buys reproducible difficulty strata and
unlimited held-out material on top.

## Why this is not `flow-corpus/`

`flow-corpus` is a **package**, not a data directory, and putting a harness-loaded corpus
inside it would muddy three of its properties at once:

- It declares itself *"fully synthetic and firewalled from any live outcome data"* — a
  claim about its own contents that a harness corpus should not be making on its behalf.
- **F-011 airgaps it from `eval_harness`**, with `flow_protocol` as the only shared
  surface. A corpus the harness loads directly is precisely the coupling that invariant
  exists to prevent.
- Its data convention is `flow-corpus/data/suites/*.jsonl`, scoped to that package's own
  calibration suites.

`examples/datasets/sample.jsonl` is the existing precedent for harness-loadable data
outside a package. `corpora/` is that idea with a version directory and a manifest.

## `testgen/v1/`

Sixty synthetic focal methods across five control-flow strata, each with a known-correct
reference implementation, a seeded mutant set, and a gold obligation set.

| File | Contents |
|---|---|
| `manifest.json` | schema version, generator seed, strata and split counts, the input grid, per-item hashes |
| `items.json` | the corpus itself — reference, mutants, obligations, and four reference suites per item |
| `eval/<kind>.jsonl` | harness-loadable records pairing each item with one reference suite |

Three properties are measured rather than asserted, which is what makes the corpus worth
trusting:

- **Mutant equivalence is decided.** A mutant is marked equivalent only if it agrees with
  the reference at every point of the manifest's input grid. A generator that labelled
  mutations equivalent by operator would put an unchecked claim into the denominator of
  every mutation score computed here.
- **Obligations carry a witness mutant.** An obligation is an equivalence class of inputs
  under which mutants detect a difference there, paired with the mutant that breaks it
  most specifically. "Covered" is then decidable by execution, and is never inferred from
  the suite being scored — which would be circular.
- **The holdout split is keyed, not shuffled.** `sha256(seed:item_id)` scaled into `[0,1)`,
  mirroring `flow-corpus/flow_corpus/partition.py`'s idiom so the scheme is one someone has
  already reviewed. Reused as an idiom rather than imported, because of the airgap above.

Regenerate with `python scripts/gen_testgen_corpus.py --write`; verify with `--check`.

## `requirements/v1/`

Twenty-five synthetic epics across authored domains, each with a declared gold
acceptance-criteria set, recorded evidence sources, and (where applicable) a
contradictory / stale / mutated negative control (F-068, ADR 0047).

| File | Contents |
|---|---|
| `manifest.json` | schema version, generator seed, split counts, per-item hashes |
| `items.json` | the corpus itself — gold ACs, evidence bytes, declared tests, control class |
| `eval/items.jsonl` | harness-loadable records pairing each epic with its generated-set stand-in |
| `eval/store.json` | the offline evidence store — `source_id` → the bytes that source *resolves to* |

`eval/store.json` is what `config/requirements_eval.yaml` names as the target's
`store_path`, so `eval-harness run --config config/requirements_eval.yaml` retrieves real
evidence with no network. It serves `store_bytes`, not `evidence_bytes`: for a **mutated**
control those two differ, and serving the original would leave the corpus unable to
demonstrate the drift its verification pass exists to catch.

The `generated` field on each eval record is a **scripted stand-in**, not a model output.
It is derived from the gold set so the shipped journey exercises all four scorers offline;
scores it produces describe the stand-in and measure no real generator. It is deliberately
imperfect and varied — a demo that scores a flat 1.0 cannot tell a working scorer from a
broken one. A real evaluation points `inner_spec` at the system under test, and the field
goes unread.

Three properties are measured rather than asserted:

- **Gold ACs are corpus-carried.** Recall is the covered fraction of the declared set,
  never inferred from the generated output.
- **Evidence is revision-scoped when pinnable.** A mutated control's store bytes
  diverge from the recorded hash so `verify_provenance` reports a provenance
  failure, distinct from a scoring failure. Unpinnable sources omit `content_sha256`.
- **The holdout split is keyed, not shuffled.** Same `sha256(seed:item_id)` idiom as
  `testgen/v1/`, reused rather than imported (F-011 airgap).

Regenerate with `python scripts/gen_requirements_corpus.py --write`; verify with `--check`.
Or run both corpora through `make corpus-check` / `make corpus-write`.
