---
name: test-completeness-guard
description: >
  Measure how many frozen public-surface names appear in a package's tests, and fail
  when that hit-rate is below an explicit floor. Use before claiming a package is
  "fully tested", when adding a sibling-package matrix census, or when a review asks
  whether exports have tests. Does not invent coverage floors.
validator_version: '2.0'
compatibility: python>=3.10
version: 1.0.0
---

# test-completeness-guard — public-surface test mention census

This skill answers a falsifiable question: **of the names frozen in
`public_surface_baseline.json` (or `backwards_compat_baseline.json`), how many appear in
the test tree?** It does not generate tests, does not invent a 95% product floor, and
does not write `HUMAN_AUDIT`. The 95% number in CI is this skill's own pytest-cov floor.

## 1. Preconditions

- A baseline JSON in the F-039 (or claude-foundation backwards-compat) shape.
- A directory of tests to scan.
- Python 3.10+, stdlib only.

## 2. Procedure

```bash
python skills/test-completeness-guard/scripts/check_completeness.py \
  --baseline path/to/public_surface_baseline.json \
  --tests path/to/tests \
  --min-hit-rate 0 \
  --format json \
  --out report.json
```

`--min-hit-rate` defaults to `CompletenessConfig.min_hit_rate` (0.0, report-only). Pass a
positive floor only when you mean it. Do not copy a 95% product claim from this skill's
CI coverage gate.

## 3. Output contract

- Exit 0 when hit-rate >= floor and the baseline was non-empty.
- Exit 1 when the floor is missed or the baseline exported nothing (vacuity refusal).
- Exit 2 on usage errors (missing files).
- JSON is sorted and path-stable (POSIX paths, no timestamps).

## 4. Validation gate

```bash
python scripts/validate_skill.py --skill . --tier structural,behavioral
```
