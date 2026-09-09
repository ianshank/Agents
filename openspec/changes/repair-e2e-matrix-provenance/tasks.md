# Tasks: repair-e2e-matrix-provenance

`[P]` = protected path.

- [x] `[P]` `tests/_e2e_matrix.py`: `GitOps`, `provenance_integrity_problems`,
      `monotonicity_problems`, waiver tables, parsers.
- [x] `[P]` `tests/test_e2e_matrix.py`: synthetic git, waiver, drop/increase, `--update`
      refuses a drop. No live-SHA pytest.
- [x] `[P]` `--check` / `--update` wiring.
- [x] ADR 0033 amendment.
- [x] `docs/e2e-matrix/ERRATA.md` disposition update.
- [ ] Next full e2e run: `--update` to restamp and drop the POSIX SHA waiver.
