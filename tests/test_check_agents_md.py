"""Tests for the ``scripts/check_agents_md.py`` per-directory ``AGENTS.md`` guard.

``scripts/`` is on ``sys.path`` (see ``tests/conftest.py``), so the guard imports flat. The
tests exercise each check against synthetic files written into ``tmp_path``, plus the public
CLI contract (exit codes 0/1/2), plus one assertion against the real repo so the shipped set
cannot silently fall out of coverage or budget.
"""

from __future__ import annotations

from pathlib import Path

import _agents_md_lib as lib
import check_agents_md as guard
import pytest

#: The repo root, resolved from this file rather than the cwd. Both repo-level tests below
#: used to default to ``--root "."``: one failed when pytest ran from elsewhere, and the
#: other passed *vacuously* off-root because it found no files to measure.
REPO_ROOT = Path(__file__).resolve().parents[1]

# A minimal file that satisfies every structural check. Individual tests break one thing.
GOOD_BODY = """# AGENTS.md - test

> A one-line purpose.

What this directory owns.

## Map

| Path | Role |
|---|---|
| `thing.py` | does the thing |

## Diagram

```mermaid
flowchart LR
  accTitle: a title
  accDescr: a sentence a screen reader can use.

  A["caller"] --> B["here"]

  classDef here fill:#e8f0fe,stroke:#1a73e8,stroke-width:2px
  class B here
```

## Rules that bite here

- **A real constraint.** And why it bites.

## Verify

```bash
make check
```

## Subagents

| Task in this directory | Agent | Why |
|---|---|---|
| Find a symbol | `explorer` | Read-only and fast |

## See also

| Doc | Read it when |
|---|---|
| [`neighbour.md`](neighbour.md) | You need the neighbouring contract |
"""


def _doc(tmp_path: Path, body: str = GOOD_BODY, budget: int = lib.TIER2_BUDGET) -> lib.Doc:
    """Build a Doc over a real file so the link check has a directory to resolve against."""
    path = tmp_path / lib.AGENTS_FILENAME
    path.write_text(body, encoding="utf-8")
    (tmp_path / "neighbour.md").write_text("neighbour\n", encoding="utf-8")
    return lib.Doc(path=path, rel=lib.AGENTS_FILENAME, budget=budget, text=body)


# --------------------------------------------------------------------------------------
# The shipped repo
# --------------------------------------------------------------------------------------


def test_repo_agents_md_set_is_clean() -> None:
    """The committed AGENTS.md set passes every check, from any working directory."""
    assert guard.main(["--root", str(REPO_ROOT)]) == guard.EXIT_OK


def test_tier_tables_have_no_overlap() -> None:
    """A directory belongs to exactly one tier."""
    assert not set(lib.TIER1_COMPONENTS) & set(lib.TIER2_SUBPACKAGES)


def test_required_dirs_carry_the_right_budget() -> None:
    """Tier 1 and Tier 2 budgets are applied to the right directories."""
    required = lib.required_dirs()
    assert required["agent-core"] == lib.TIER1_BUDGET
    assert required["src/eval_harness/core"] == lib.TIER2_BUDGET
    assert len(required) == len(lib.TIER1_COMPONENTS) + len(lib.TIER2_SUBPACKAGES)


def test_nested_budgets_sit_below_the_root_ceiling() -> None:
    """Nested files exist to stay local; they may never be laxer than the root."""
    assert lib.TIER2_BUDGET < lib.TIER1_BUDGET < lib.ROOT_BUDGET


def test_dot_claude_is_not_a_tier_directory() -> None:
    """`.claude/AGENTS.md` loads eagerly, so it is not a lazily-loaded directory doc."""
    assert ".claude" not in lib.TIER1_COMPONENTS
    assert ".claude" not in lib.TIER2_SUBPACKAGES
    assert ".claude" in lib.COVERED_BY_PARENT


def test_eager_files_are_all_outside_the_tier_table() -> None:
    """An eagerly-loaded file must not also carry a per-tier budget: the sum is what binds."""
    tiers = set(lib.TIER1_COMPONENTS) | set(lib.TIER2_SUBPACKAGES)
    for rel in lib.EAGER_FILES:
        assert str(Path(rel).parent) not in tiers


def test_eager_budget_passes_for_the_real_repo() -> None:
    """What the committed repo actually loads at session start is within the ceiling."""
    assert (REPO_ROOT / lib.AGENTS_FILENAME).is_file()  # else the assertion below is vacuous
    assert lib.check_eager_budget(REPO_ROOT) == []


def test_eager_budget_sums_across_files(tmp_path: Path) -> None:
    """Two files each under the ceiling can still bust it together."""
    (tmp_path / ".claude").mkdir()
    (tmp_path / lib.AGENTS_FILENAME).write_text("x\n" * 150, encoding="utf-8")
    (tmp_path / ".claude" / lib.AGENTS_FILENAME).write_text("y\n" * 150, encoding="utf-8")
    findings = lib.check_eager_budget(tmp_path)
    assert len(findings) == 1
    assert findings[0].check == "eager-budget"
    assert "300 lines load at session start" in findings[0].detail


def test_eager_budget_ignores_a_missing_file(tmp_path: Path) -> None:
    """Only the root exists in most checkouts; that is not a violation."""
    (tmp_path / lib.AGENTS_FILENAME).write_text("x\n" * 10, encoding="utf-8")
    assert lib.check_eager_budget(tmp_path) == []


def test_eager_budget_skips_an_unreadable_file(tmp_path: Path) -> None:
    """A non-UTF-8 file is reported by load_docs, not double-reported here."""
    (tmp_path / lib.AGENTS_FILENAME).write_bytes(b"\xff\xfe not utf-8")
    assert lib.check_eager_budget(tmp_path) == []


# --------------------------------------------------------------------------------------
# Individual checks
# --------------------------------------------------------------------------------------


def test_good_body_passes_every_structural_check(tmp_path: Path) -> None:
    doc = _doc(tmp_path)
    assert lib.check_sections(doc) == []
    assert lib.check_mermaid(doc) == []
    assert lib.check_budget(doc) == []
    assert lib.check_lint_leakage(doc) == []
    assert lib.check_blind_references(doc) == []
    assert lib.check_links(doc, tmp_path) == []


def test_budget_violation_reports_the_overage(tmp_path: Path) -> None:
    doc = _doc(tmp_path, GOOD_BODY + "\nfiller\n" * 200)
    findings = lib.check_budget(doc)
    assert len(findings) == 1
    assert findings[0].check == "budget"
    assert f"{lib.TIER2_BUDGET}-line ceiling" in findings[0].detail


def test_missing_section_is_reported(tmp_path: Path) -> None:
    doc = _doc(tmp_path, GOOD_BODY.replace("## Verify", "## Something else"))
    details = [f.detail for f in lib.check_sections(doc)]
    assert any("'## Verify'" in d for d in details)


def test_sections_out_of_order_are_reported(tmp_path: Path) -> None:
    body = GOOD_BODY.replace("## Map", "## TEMP").replace("## Diagram", "## Map")
    doc = _doc(tmp_path, body.replace("## TEMP", "## Diagram"))
    assert any(f.detail.startswith("sections out of order") for f in lib.check_sections(doc))


@pytest.mark.parametrize(
    ("removed", "expected"),
    [("  accTitle: a title\n", "accTitle:"), ("  accDescr: a sentence a screen reader can use.\n", "accDescr:")],
)
def test_mermaid_requires_accessibility_metadata(tmp_path: Path, removed: str, expected: str) -> None:
    doc = _doc(tmp_path, GOOD_BODY.replace(removed, ""))
    assert any(expected in f.detail for f in lib.check_mermaid(doc))


def test_mermaid_missing_entirely_is_reported(tmp_path: Path) -> None:
    body = GOOD_BODY.split("## Diagram")[0] + "## Diagram\n\n## Rules that bite here\n\n- x\n"
    doc = _doc(tmp_path, body)
    assert any("no ```mermaid diagram" in f.detail for f in lib.check_mermaid(doc))


def test_mermaid_unknown_diagram_type_is_reported(tmp_path: Path) -> None:
    doc = _doc(tmp_path, GOOD_BODY.replace("flowchart LR", "doodle LR"))
    assert any("unrecognised type" in f.detail for f in lib.check_mermaid(doc))


def test_mermaid_unterminated_fence_is_reported(tmp_path: Path) -> None:
    body = GOOD_BODY.replace("  class B here\n```\n", "  class B here\n")
    doc = _doc(tmp_path, body)
    assert any("unterminated" in f.detail for f in lib.check_mermaid(doc))


def test_mermaid_non_ascii_label_is_reported(tmp_path: Path) -> None:
    """GitHub's renderer breaks on emoji and extended characters inside labels."""
    doc = _doc(tmp_path, GOOD_BODY.replace('B["here"]', 'B["hère \U0001f600"]'))
    assert any("non-ASCII" in f.detail for f in lib.check_mermaid(doc))


def test_empty_mermaid_block_is_reported(tmp_path: Path) -> None:
    body = GOOD_BODY.split("## Diagram")[0] + "## Diagram\n\n```mermaid\n```\n\n## Rules that bite here\n\n- x\n"
    doc = _doc(tmp_path, body)
    assert any("is empty" in f.detail for f in lib.check_mermaid(doc))


def test_dead_relative_link_is_reported(tmp_path: Path) -> None:
    doc = _doc(tmp_path, GOOD_BODY.replace("neighbour.md", "gone.md"))
    findings = lib.check_links(doc, tmp_path)
    assert len(findings) == 1
    assert "gone.md" in findings[0].detail


@pytest.mark.parametrize(
    "target",
    ["https://example.com", "http://example.com", "mailto:a@b.c", "#anchor", "/abs/path", "glob/**"],
)
def test_non_local_link_targets_are_skipped(tmp_path: Path, target: str) -> None:
    """External links, anchors, absolutes and globs are not drift signals."""
    doc = _doc(tmp_path, GOOD_BODY.replace("(neighbour.md)", f"({target})"))
    assert lib.check_links(doc, tmp_path) == []


def test_link_anchor_and_title_are_stripped(tmp_path: Path) -> None:
    """``[a](file.md#section "title")`` resolves against ``file.md``."""
    doc = _doc(tmp_path, GOOD_BODY.replace("(neighbour.md)", '(neighbour.md#part "a title")'))
    assert lib.check_links(doc, tmp_path) == []


@pytest.mark.parametrize("word", ["snake_case", "PascalCase", "camelCase", "indentation", "import ordering"])
def test_lint_leakage_is_rejected(tmp_path: Path, word: str) -> None:
    """Restating a rule ruff already enforces is dead weight."""
    doc = _doc(tmp_path, GOOD_BODY.replace("- **A real constraint.**", f"- Use {word} here."))
    assert any(f.check == "lint-leakage" for f in lib.check_lint_leakage(doc))


def test_blind_reference_without_a_trigger_is_rejected(tmp_path: Path) -> None:
    """A 'See also' row citing a path with no 'Read it when' cell gets ignored by agents."""
    doc = _doc(
        tmp_path,
        GOOD_BODY.replace(
            "| [`neighbour.md`](neighbour.md) | You need the neighbouring contract |",
            "| [`neighbour.md`](neighbour.md) |  |",
        ),
    )
    findings = lib.check_blind_references(doc)
    assert len(findings) == 1
    assert findings[0].check == "blind-reference"


def test_blind_reference_check_skips_a_file_without_the_section(tmp_path: Path) -> None:
    doc = _doc(tmp_path, GOOD_BODY.replace("## See also", "## Elsewhere"))
    assert lib.check_blind_references(doc) == []


# --------------------------------------------------------------------------------------
# Coverage
# --------------------------------------------------------------------------------------


def test_coverage_reports_a_missing_required_file(tmp_path: Path) -> None:
    for rel in lib.TIER1_COMPONENTS:
        (tmp_path / rel).mkdir(parents=True, exist_ok=True)
    findings = lib.check_coverage(tmp_path)
    assert any(f.detail == "required but missing" for f in findings)


def test_coverage_reports_a_directory_that_does_not_exist(tmp_path: Path) -> None:
    findings = lib.check_coverage(tmp_path)
    assert any("does not exist" in f.detail for f in findings)


def test_covered_directory_must_not_carry_a_file(tmp_path: Path) -> None:
    """A skill's SKILL.md is already its contract; a second file invites contradiction."""
    skill = tmp_path / "skills" / "demo-skill"
    skill.mkdir(parents=True)
    (skill / lib.AGENTS_FILENAME).write_text(GOOD_BODY, encoding="utf-8")
    findings = lib.check_coverage(tmp_path)
    assert any("must NOT exist" in f.detail for f in findings)


def test_a_stray_file_nested_below_a_covered_dir_is_reported(tmp_path: Path) -> None:
    """The forbidden arrangement is a second instruction file beside a SKILL.md.

    ``skills/*`` matched only ``skills/<skill>``, so a file one level deeper -- exactly where
    a skill keeps its scripts -- was invisible to the guard that forbids it.
    """
    nested = tmp_path / "skills" / "demo" / "scripts"
    nested.mkdir(parents=True)
    (nested / lib.AGENTS_FILENAME).write_text(GOOD_BODY, encoding="utf-8")
    findings = lib.check_coverage(tmp_path)
    assert any(f.path == "skills/demo/scripts/AGENTS.md" for f in findings)


def test_a_required_dir_is_not_also_forbidden(tmp_path: Path) -> None:
    """``skills/**`` matches ``skills`` itself, which is Tier 1.

    Without required-wins precedence the guard would demand skills/AGENTS.md and forbid it in
    the same run. Every directory must be in exactly one state.
    """
    (tmp_path / "skills").mkdir()
    (tmp_path / "skills" / lib.AGENTS_FILENAME).write_text(GOOD_BODY, encoding="utf-8")
    covered = [p.relative_to(tmp_path).as_posix() for p, _ in lib._covered_dirs(tmp_path)]
    assert "skills" not in covered
    assert not [f for f in lib.check_coverage(tmp_path) if f.path == "skills/AGENTS.md"]


def test_covered_by_parent_reasons_are_all_populated() -> None:
    """Every recorded exemption states why, so the absence reads as a decision."""
    assert all(reason.strip() for reason in lib.COVERED_BY_PARENT.values())


# --------------------------------------------------------------------------------------
# CLI contract
# --------------------------------------------------------------------------------------


def test_cli_reports_violations_and_exits_one(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert guard.main(["--root", str(tmp_path)]) == guard.EXIT_VIOLATION
    assert "FAIL" in capsys.readouterr().out


def test_cli_missing_root_is_a_usage_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert guard.main(["--root", str(tmp_path / "nope")]) == guard.EXIT_USAGE_ERROR
    assert "usage error" in capsys.readouterr().err


def test_cli_json_output_is_parseable(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    import json

    guard.main(["--root", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload and {"path", "check", "detail"} == set(payload[0])


def test_cli_paths_only_emits_bare_paths(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    guard.main(["--root", str(tmp_path), "--paths-only"])
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln]
    assert lines == sorted(set(lines))
    assert all("[" not in ln for ln in lines)


def test_cli_verbose_flag_is_accepted(tmp_path: Path) -> None:
    assert guard.main(["--root", str(tmp_path), "-v"]) == guard.EXIT_VIOLATION


def test_unreadable_file_is_a_read_finding(tmp_path: Path) -> None:
    """A non-UTF-8 file is an operator error surfaced as a finding, not a traceback."""
    (tmp_path / lib.AGENTS_FILENAME).write_bytes(b"\xff\xfe not utf-8")
    _, findings = lib.load_docs(tmp_path)
    assert [f.check for f in findings] == ["read"]


def test_finding_render_is_human_readable() -> None:
    rendered = lib.Finding("a/AGENTS.md", "budget", "too long").render()
    assert rendered == "  a/AGENTS.md: [budget] too long"
