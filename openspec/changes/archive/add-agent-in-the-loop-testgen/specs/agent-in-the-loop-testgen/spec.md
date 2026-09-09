# Spec: agent-in-the-loop test generation

## Purpose

Accept agent-authored suites into the existing F-065 execution and scoring path without presenting corpus self-grades as agent results.

## Requirements

### Generator Isolation
The generator SHALL NOT receive `inputs.suite`. The pipeline MUST copy the item and drop that key before generate. A generator whose only trick is copying `item.inputs["suite"]` MUST fail closed. The original item MUST NOT be mutated.

## Scenarios

### Happy path — generated suite executes
Given a focal method and obligations
When the pipeline target generates a suite and executes it in-process via `run_generated_suite`
Then F-065 scorers receive the same evidence shape as corpus-supplied suites
And the run record attributes the suite to the generator attempt (hash / id), not to the corpus reference suite.

### Held-out isolation
Given a held-out item id
When an offline CI job runs the agent-in-the-loop profile
Then configuration that points the generator training loop at held-out items is rejected
And Deck B reporting configs use only the sequestered split.

### Fail closed — malformed generation
Given a generator that returns a non-suite or empty collect
When the pipeline runs
Then execution does not open sockets
And scorers report not-applicable or failure per existing F-065 purity rules
And no partial silent success is written.

### Offline DI
Given injected fake generator and fake execution seams
When tests run without network
Then results are deterministic across two runs (modulo explicit timestamps if any).

### Opt-in compatibility
Given legacy `config/testgen_eval.yaml` (corpus-supplied suite)
When it runs unchanged
Then behaviour remains the Deck A+ calibration path and does not require a generator.
