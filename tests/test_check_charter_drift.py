"""Tests for the ``scripts/check_charter_drift.py`` charter-drift guard.

``scripts/`` is on ``sys.path`` (see ``tests/conftest.py``), so the guard imports flat.
The tests exercise the public CLI contract (exit codes 0/1/2) against synthetic charters
written into ``tmp_path``, plus the link-classification helpers directly — asserting the
false-positive cases the guard is designed to tolerate (globs, external links, anchors, and
slashed inline-code identifiers) do NOT count as drift.
"""

from __future__ import annotations

from pathlib import Path

import check_charter_drift as guard
import pytest


def _write_charter(directory: Path, body: str) -> Path:
    """Write a charter file into *directory* and return its path."""
    charter = directory / "CHARTER.md"
    charter.write_text(body, encoding="utf-8")
    return charter


def test_real_charter_has_no_drift() -> None:
    """The shipped docs/CHARTER.md must have zero dead references."""
    assert guard.main([]) == 0


def test_dead_file_link_detected(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A link to a non-existent sibling file is drift (exit 1)."""
    charter = _write_charter(tmp_path, "See [gone](missing_file.md) for details.\n")
    assert guard.main(["--charter", str(charter)]) == 1
    out = capsys.readouterr().out
    assert "missing_file.md" in out
    assert "FAIL" in out


def test_missing_adr_link_detected(tmp_path: Path) -> None:
    """An ADR-style link to a non-existent decision file is drift (exit 1)."""
    charter = _write_charter(tmp_path, "Per [ADR 9999](decisions/9999-nope.md) this is gone.\n")
    assert guard.main(["--charter", str(charter)]) == 1


def test_live_links_and_non_paths_pass(tmp_path: Path) -> None:
    """A charter whose only concrete link resolves — with globs, externals, anchors,
    and slashed inline-code alongside it — is clean (exit 0)."""
    (tmp_path / "sibling.md").write_text("real\n", encoding="utf-8")
    body = (
        "Live link: [here](sibling.md).\n"
        "Glob (skipped): [protected](scripts/validations/**).\n"
        "External (skipped): [changelog](https://keepachangelog.com/).\n"
        "Anchor (skipped): [top](#status--purpose).\n"
        "Inline code is never a link: `ship/hold/escalate`, `LANGFUSE_*`, `config/**`.\n"
    )
    charter = _write_charter(tmp_path, body)
    assert guard.main(["--charter", str(charter)]) == 0


def test_usage_error_on_missing_charter(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Pointing the guard at a non-existent charter is a usage error (exit 2)."""
    missing = tmp_path / "nope.md"
    assert guard.main(["--charter", str(missing)]) == guard.EXIT_USAGE_ERROR
    assert "usage error" in capsys.readouterr().err


def test_directory_link_is_live(tmp_path: Path) -> None:
    """A link target that resolves to an existing directory is treated as live."""
    (tmp_path / "decisions").mkdir()
    charter = _write_charter(tmp_path, "Records live in [decisions](decisions).\n")
    assert guard.main(["--charter", str(charter)]) == 0


@pytest.mark.parametrize(
    ("target", "checkable"),
    [
        ("../AGENTS.md", True),
        ("decisions/0004-auto-fix-loop.md", True),
        ("https://example.com", False),
        ("http://example.com", False),
        ("mailto:x@example.com", False),
        ("//cdn.example.com/x", False),
        ("#anchor", False),
        ("scripts/validations/**", False),
        ("config/**", False),
        ("weird[glob].md", False),
        ("", False),
    ],
)
def test_is_checkable_local_link(target: str, checkable: bool) -> None:
    """Classification: only concrete local paths are checkable references."""
    assert guard._is_checkable_local_link(target) is checkable


def test_extract_local_targets_dedupes_and_strips_fragments() -> None:
    """Targets are de-duplicated, fragment/query stripped, non-links ignored."""
    text = (
        "[a](../AGENTS.md) and again [a2](../AGENTS.md#heading) "
        "and [b](README.md?x=1) but not `inline/slash/code` or [ext](https://x.io)."
    )
    assert guard.extract_local_targets(text) == ["../AGENTS.md", "README.md"]


def test_find_dead_links_returns_structured_findings(tmp_path: Path) -> None:
    """find_dead_links reports each missing target with its resolved POSIX path + reason."""
    charter = _write_charter(tmp_path, "[x](nope_a.md) [y](nope_b.md)\n")
    dead = guard.find_dead_links(charter)
    assert {d.target for d in dead} == {"nope_a.md", "nope_b.md"}
    assert all(d.resolved.endswith(".md") for d in dead)
    assert all(d.reason == "missing" for d in dead)


def test_target_escaping_repo_root_is_dead(tmp_path: Path) -> None:
    """A link resolving OUTSIDE the repo root is dead even if the OS path exists.

    The containment root is pinned deterministically with a ``.git`` marker so the test does
    not depend on where the temp dir lives.
    """
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)  # pins _containing_root() at `repo`
    (tmp_path / "outside.md").write_text("real but out of repo\n", encoding="utf-8")
    charter = _write_charter(repo, "Escape attempt: [x](../outside.md)\n")

    assert guard.main(["--charter", str(charter)]) == 1
    dead = guard.find_dead_links(charter)
    assert [d.reason for d in dead] == ["outside repo root"]


def test_in_repo_reference_still_live_with_git_root(tmp_path: Path) -> None:
    """Within the pinned root, an existing target is still live (no false positive)."""
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "NEXT_STEPS.md").write_text("x\n", encoding="utf-8")
    charter = _write_charter(repo, "See [next](NEXT_STEPS.md).\n")
    assert guard.main(["--charter", str(charter)]) == 0


def test_titled_link_url_is_extracted(tmp_path: Path) -> None:
    """A CommonMark title must not corrupt the checked path (live link stays live)."""
    (tmp_path / "readme.md").write_text("x\n", encoding="utf-8")
    charter = _write_charter(tmp_path, 'See [readme](readme.md "Project readme").\n')
    assert guard.main(["--charter", str(charter)]) == 0


def test_angle_bracketed_target_is_unwrapped() -> None:
    """<...> targets are unwrapped, preserving internal spaces."""
    assert guard.extract_local_targets("[a](<some file.md>)") == ["some file.md"]


def test_reference_style_dead_link_detected(tmp_path: Path) -> None:
    """A dead target hidden in a reference-style link definition is still caught (exit 1)."""
    body = "Per [ADR 9999][adr] this holds.\n\n[adr]: decisions/9999-nope.md\n"
    charter = _write_charter(tmp_path, body)
    assert guard.main(["--charter", str(charter)]) == 1


def test_reference_style_live_link_passes(tmp_path: Path) -> None:
    """A reference definition pointing at an existing file is clean (exit 0)."""
    (tmp_path / "real.md").write_text("x\n", encoding="utf-8")
    charter = _write_charter(tmp_path, "Uses [thing][t].\n\n[t]: real.md\n")
    assert guard.main(["--charter", str(charter)]) == 0


def test_absolute_targets_are_skipped(tmp_path: Path) -> None:
    """Absolute paths are not resolved against the filesystem root — neither flagged nor
    treated as live-by-accident. A charter with only absolute targets is clean."""
    charter = _write_charter(tmp_path, "[a](/docs/CHARTER.md) and [b](/etc/passwd)\n")
    assert guard.extract_local_targets(charter.read_text(encoding="utf-8")) == []
    assert guard.main(["--charter", str(charter)]) == 0


def test_non_utf8_charter_is_usage_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A charter that exists but is not valid UTF-8 is a usage error (exit 2), not drift."""
    charter = tmp_path / "CHARTER.md"
    charter.write_bytes(b"\xff\xfe invalid \x80 bytes [x](y.md)")
    assert guard.main(["--charter", str(charter)]) == guard.EXIT_USAGE_ERROR
    assert "usage error" in capsys.readouterr().err
