# `corpora/` — versioned evaluation corpora loaded by the harness

Frozen, generated datasets that `eval_harness` loads through its shipped dataset
components. Each corpus lives under `corpora/<name>/<version>/` with a `manifest.json`
carrying its schema version, generator seed, and a content hash per item.

| Corpus | Generator | Loaded by |
|---|---|---|
| [`testgen/v1/`](testgen/v1/) | [`scripts/gen_testgen_corpus.py`](../scripts/gen_testgen_corpus.py) | [`config/testgen_eval.yaml`](../config/testgen_eval.yaml) via the `jsonl` dataset |

## What belongs here

Data that the **harness** loads: generated, reproducible, and verifiable against its own
manifest. `python scripts/gen_testgen_corpus.py --check` regenerates a corpus and fails if
the committed bytes differ, so a hand-edited item is caught rather than trusted.

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
