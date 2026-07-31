# 0004 — Implement the append-only manifest-diff gate as a checked-in baseline

- Status: **Accepted.**
- Date: 2026-07-21
- Related: ADR 0001 (plugin + marketplace packaging; decision point 4 is the contract
  this ADR implements); ADR 0002 (hook fail modes; hooks are one of the component
  kinds diffed here); ADR 0003 (release gate is separate from the merge gate — this
  check follows the same split).

## Context

ADR 0001 decision point 4 states: "Component names are append-only within a major
version. Renaming or removing a released skill, subagent, or hook requires a major
version bump. A release-gate manifest diff enforces this against the previous minor's
public surface." No code implementing that diff existed — `CLAUDE.md`,
`CHANGELOG.md`'s `[1.0.0]` entry, and `docs/architecture.md`'s CI container description
all referenced a "backwards-compat fixture" that was documentation only.

Consumers pin the plugin via marketplace `ref`/`sha` (ADR 0001 pt. 3); an unenforced
rename or removal of a skill, subagent, or hook script could silently break a pinned
consumer's install with no warning at release time.

There are no git tags anywhere in this monorepo (`claude-foundation` is currently
staged inside `ianshank/Agents`, pending extraction), so diffing against a tagged
prior release isn't viable yet. The parent monorepo already solves an analogous
problem — Python public-surface stability across 5 sibling packages — with a
checked-in JSON baseline plus a `--update` regeneration flag
(`/home/user/Agents/tests/test_public_surface.py` +
`tests/public_surface_baseline.json`, the F-039 guard). That pattern is the direct
precedent for this decision.

## Decision

1. **`foundation_tools.backwards_compat`** is a new `foundation_tools` CLI module
   following the existing template (`validate.py`/`scan.py`/`eval_gate.py`): pure
   `check_*`/`extract_*`/`diff_*` functions, `get_logger("foundation.backwards_compat")`,
   `main(argv) -> int` with exit codes 0/1/2.
2. **The public surface** tracked is three component kinds: skill names
   (`skills/*/SKILL.md` frontmatter `name`), subagent names (`agents/**/*.md`
   frontmatter `name`, recursive), and hook script basenames (parsed from
   `hooks/hooks.json` matcher `command` strings — hooks have no dedicated name field,
   so the script filename is the de facto stable identity already used informally in
   `docs/architecture.md`'s hook table).
3. **Baseline location: `tests/backwards_compat_baseline.json`**, not colocated inside
   the installed `foundation_tools` package. The package ships no `package-data`
   configuration in `pyproject.toml`, so package-colocated data would silently fail to
   install; more fundamentally, this data describes the repo's own release history and
   is only ever consumed from a source checkout in CI (`--root .`), never by an
   installed consumer — the same reasoning that puts `public_surface_baseline.json` in
   `tests/` in the parent repo.
4. **Diff semantics are asymmetric by design**: a component present in the baseline
   but absent from the live tree is a finding *unless* `plugin.json`'s major version
   has increased since the baseline was last frozen; a component present in the live
   tree but absent from the baseline is never a finding. This diverges deliberately
   from the parent's `test_public_surface.py` (which fails on unfrozen *additions*
   too, forcing immediate `--update`): ADR 0001 frames the baseline refresh as a
   pre-release action, and the compatibility contract itself only restricts
   removals/renames, not additions — failing merges over routine new skills/agents
   would contradict that contract's own scope.
5. **Renames are indistinguishable from remove+add** at this granularity, matching the
   parent precedent — a rename is conservatively treated as a blocked removal (plus a
   silent, harmless addition) unless accompanied by a major bump. This is intentional:
   it's the correct, safe default given the contract's intent.
6. **Gates releases only, not merges** — wired into the `release-gate` job in
   `.github/workflows/ci.yml` (tag-triggered, same `if: startsWith(github.ref,
   'refs/tags/v')` condition `eval_gate` already uses), not `merge-gate`. Components
   legitimately get added/renamed mid-development before a release freezes them; only
   the release boundary should enforce the frozen baseline. The module's own unit
   tests still run on every merge via the existing `pytest` step.
7. **`--update` is a manual, pre-tag operation**, not automatic: `python -m
   foundation_tools.backwards_compat --root . --update` regenerates the baseline from
   the live tree and the current `plugin.json` major, to be committed as its own
   reviewable diff — per ADR 0001's "deliberate, reviewable configuration diffs, never
   silent."
8. **Known limitation, accepted for v1**: if a maintainer bumps the major version
   without running `--update` in the same release, and a component is later added and
   then removed entirely within that stale window, the removal would never be captured
   against the (still pre-bump) baseline. The gate mitigates this with a non-failing
   `logger.warning` when the live major exceeds the baseline's recorded major, and
   `CLAUDE.md` documents the required manual step — full enforcement (e.g. hard-failing
   until the baseline's recorded major matches) is deferred rather than added
   speculatively.

## Consequences

- A release-gate CI run now fails with a clear per-kind, per-name message
  (`"agents: removed without a major version bump (baseline major 1, current 1):
  ['explorer']"`) if a tagged release would silently drop a component a consumer may
  be relying on.
- Maintaining the compatibility contract now costs one explicit step per release that
  intentionally removes/renames a component: run `--update`, review the JSON diff,
  commit it alongside the major version bump.
- This ADR does not amend ADR 0001 — ADR 0002 and ADR 0003 show no precedent for
  editing an ADR after acceptance in this repo, so ADR 0001's own Decision and
  Consequences text is left untouched; this ADR is cross-referenced from it instead.
