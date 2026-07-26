# Tasks: add-measurement-harness-wedge

Ordered per `./review.md`. Owners use the fleet contract in `openspec/AGENTS.md`. `[P]` =
protected path → needs `eval-change-approved` + CODEOWNERS. Coverage floors:
`make -C agent-core check` ≥ 95%, `scripts/` ≥ 85%.

**Note on `[P]` isolation.** `scripts/eval_protected_paths.py:29-46` protects root `tests/**`
*and* every sibling package's `tests/**`, plus `architecture.yaml`. Every test file here is
therefore `[P]`, and strict per-PR isolation would land agent-core below its 95% floor — a
guaranteed red gate. Use the PR #82 shape: one labelled PR, protected changes isolated into
their own **commits**.

**F-IDs and ADR numbers are claimed at land.** Next free today: F-048, ADR 0027. Do not
reserve — every ID the 2026-07-03 plan pre-assigned drifted, and `feat/F-040-soak-stats` still
holds F-040 in flight.

## WS-0 — Hygiene gate (BLOCKING)

- [ ] 0.1 **HUMAN hard-stop:** written confirmation the `sk-lf-e220…` / `pk-lf-ad61…` pair is
      revoked. The stranded ADR *asserts* this; nobody verified it. Nothing merges first.
- [ ] 0.2 Rebase (do not merge) the salvage from `origin/feat/F-038-gitleaks`: 155 behind /
      2 ahead, 5 conflicts (`CHANGELOG.md`, `NEXT_STEPS.md`, `features.yaml`, `progress.md`,
      add/add on `scripts/validations/F_038.py`). `HARNESS_SPEC.md` auto-merges clean.
- [ ] 0.3 Redact → `<REDACTED — rotated, see incident record>`: `HARNESS_SPEC.md:311-312`,
      `docs/decisions/0003-langfuse-integration.md:7-8`, `progress.md:280`.
      Leave `NEXT_STEPS.md:257` — it covers the dashboard/`.env`, not the doc scrub, and is
      not false.
- [ ] 0.4 Re-number the no-history-rewrite ADR (0019 → size-budget, 0020 →
      deterministic-generator-skills; both were pre-assigned to it and both drifted). Strike
      the unverified "confirmed before this change merged" sentence; cite 0.1 instead.
- [ ] 0.5 `[P]` `.gitleaks.toml` + gitleaks step in `quality-gates.yml`: **fail-closed on the
      working tree, report-only on history** (keys are already public in remote history;
      rotation is the mitigation and a rewrite invalidates every clone, PR base, pinned
      `implemented_in` SHA, and the `merge-gate-data` lineage).
- [ ] 0.6 `[P]` `scripts/validations/F_0NN.py` — config exists, workflow is fail-closed, no
      `sk-lf-`/`pk-lf-` literal survives. Verify with a seeded canary on a throwaway branch.
- [ ] 0.7 Correct `SECURITY.md:53` ("Secret scanning runs in CI" — untrue until 0.5 lands) and
      `:49-51` (Snyk; no workflow references it, CHARTER §5 lists it as future). `README.md:9`
      and `:76` repeat both.
- [ ] 0.8 `.gitignore:62` is `*.html`. Allowlist the sample-report and fixture paths **before**
      WS-2 writes any — the failure mode is silent. Same for `merge_outcomes.jsonl`,
      `context.json`, `agent.json`.

## WS-1 — External PR-history ingestion

- [ ] 1.1 `agent_core/pr_history/` subpackage mirroring `store_sync/`: frozen config
      dataclasses (no call-site literals), `PRHistorySource` Protocol, `IngestResult` carrying
      `truncated` / `reason` / per-reason `skipped`.
- [ ] 1.2 `LocalGitSource` — offline, `run_failsafe`, `--head-ref-from
      {merge-subject,trailer,none}` for squash-merge repos. Parse traps: `-z` numstat renames,
      binary `-\t-\tpath`, non-ASCII paths.
- [ ] 1.3 `GhCliSource` via `gh pr list --json …`. Fail closed when scopes are unverifiable;
      `--token-env NAME` only, never a `--token` flag.
- [ ] 1.4 Partner-supplied attribution: repeatable `--agent-prefix`, `--test-glob`,
      `--protected-glob` injected at the CLI layer. No `config/**` edit.
- [ ] 1.5 `scripts/pr_ingest.py` reusing `AgentIdentity`, `compute_confidence`, and
      `merge_gate_context.build_context` (one call reuses domain classification, the `human/`
      namespace, and the human-confidence-is-0.0 rule). If `compute_confidence` is refactored,
      pin it with a golden table — it computes every `raw_confidence` in the store.
- [ ] 1.6 `[P]` Write boundary: `PassiveOnlyStore`, a test rejecting `"human_audit"` **and** an
      unknown string, and an AST absence check over the ingestion modules.
- [ ] 1.7 `[P]` Fixtures + golden tests + determinism (two runs identical modulo timestamps).
- [ ] 1.8 `[P]` Injection-resistance test: instruction-like PR bodies render inert and escaped.

## WS-2 — Honest report surface

- [ ] 2.1 `agent_core/discrimination.py::auroc_interval` (Hanley–McNeil, closed form,
      deterministic, `None` on degeneracy). **No AUROC CI exists in the repo today** and the
      wedge is unmeetable without one. New module, not `calibration.py` — keeps the TCB at
      zero edits.
- [ ] 2.2 Truth-side selector so passive signals can serve as the *label* in
      `proxy_eval.build_dataset`, which today admits only `HUMAN_AUDIT` (`:150-157`) and
      therefore measures nothing externally. Must never write or alias `HUMAN_AUDIT`; results
      stay DIAGNOSTIC.
- [ ] 2.3 `calibration_report_html.py` — self-contained, **no `<script>` element**, every
      interpolation through `_esc()`. Leads with a degeneracy banner (assert its index precedes
      the first table). Renders the ingest manifest as provenance.
- [ ] 2.4 New `SliceReport` fields **appended last** — `analyze_slice`'s `n == 0` branch uses
      14 positional args and would silently mis-bind.
- [ ] 2.5 Report states in-band that `raw_confidence` is a diff-shape heuristic, not agent
      introspection (ADR 0023 §1). No new binning — reuse `reliability_bins` (G2).
- [ ] 2.6 `[P]` **Separate TCB PR:** G3 in `outcome_store.py` — return a no-evidence sentinel,
      not `0.0`, for empty upper bins. Strictly fail-closed.

## WS-3 — Distribution

- [ ] 3.1 ~~LICENSE/NOTICE~~ — already present in all seven package dirs; verify only. But
      `NOTICE:15-19` flattens the **ELv2** `arize-phoenix-evals` extra in with permissive ones;
      correct or drop it from the promoted path.
- [ ] 3.2 First `[project.scripts]` for `agent-core`. Note the root distribution excludes
      `agent-core` entirely (`packages.find where = ["src"]`), there is **no publish workflow**,
      and `git tag` returns zero — WS-3 is larger than "add a console script."
- [ ] 3.3 Verify in a fresh container: pipx install from a git ref, then `--help` offline.

## WS-4 — External shadow mode (thin delta)

- [ ] 4.1 `[P]` `shadow-external` job beside the existing byte-identical `shadow` job. Reuse
      `merge_gate_ci._append_audit`.
- [ ] 4.2 **Hard invariant:** never `vars.MERGE_GATE_STORE`, never `store_sync push` — mixing a
      partner's records into this corpus is the pool-poisoning `domains.py` prevents. Assert in
      the F-ID gate. Also force an explicit remote: `store_sync` defaults to
      `origin`/`merge-gate-data` and would publish third-party records into this repo.
- [ ] 4.3 Dry run against a public OSS repo; assert zero writes.

## WS-5 — Positioning

- [ ] 5.1 README section — **additive**. CHARTER §1 delegates the vision statement to the
      README, so replacing its opening silently amends the charter, and
      `check_charter_drift.py` cannot detect it (it only verifies link targets resolve).
- [ ] 5.2 Quickstart: fresh clone → first report ≤ 10 min, timed.
- [ ] 5.3 Commit one sample report with its degeneracy findings shown honestly — that is the
      point, not an embarrassment. Note `domain` leaks a partner's module taxonomy; use a
      public repo.
- [ ] 5.4 Tag `v0.1.0` (the repo currently has zero tags).

## Human-owned (not implementation tasks)

- [ ] H.1 Rotation confirmation — **blocks WS-0**.
- [ ] H.2 CHARTER §3 amendment + GOVERNANCE sign-off — the wedge expands scope past *"not an
      autonomous merge bot… not a general observability platform."* **Blocks WS-5.**
- [ ] H.3 Rename before publishing — `langfuse-eval-harness` / `claude-foundation-tools` are
      third-party marks; Apache-2.0 §6 grants no trademark license. All candidates unclaimed on
      PyPI, so this is a free choice now.
- [ ] H.4 IP / invention-assignment review — gates commercial distribution.
- [ ] H.5 Decide the ELv2 `phoenix-evals` question (H.1 of WS-3.1).
- [ ] H.6 Discovery calls; recruit a design partner.

## Follow-on (separate change; not this one)

- [ ] `GitHubRestSource` with pagination/SSRF hardening, if a partner needs it over `gh`.
- [ ] G1 — make `GatePolicyConfig` reachable from config/CLI so risk appetite is tunable.
- [ ] G2 — consolidate the four equal-width binning implementations (blocked on deciding what
      `build_domain_models` should do with an out-of-contract stored score).
- [ ] Repair the 10 unresolvable `implemented_in` refs before any release adopts `--strict-git`.

## Archive

- [ ] Each F-ID lands with `status: done` + `implemented_in:<sha>`; `scripts/validate.py
      --tier fast` green; `make check-all` green; then move this change under
      `openspec/changes/archive/` (which does not exist yet — this would create it).
- [ ] Evaluate the OpenSpec spike per `docs/openspec-spike.md` (keep vs `rm -rf openspec/`).
