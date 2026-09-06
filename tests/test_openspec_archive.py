"""Tests for scripts/openspec_archive.py — rewrite outbound links, not a blind ../."""

from __future__ import annotations

from pathlib import Path

import pytest

import openspec_archive as arch


def _mv(_repo: Path, src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)


def test_rewrite_outbound_gains_one_segment_nested_specs_gain_two() -> None:
    old_root = Path("/repo/openspec/changes/foo")
    new_file = Path("/repo/openspec/changes/archive/foo/proposal.md")
    old_file = old_root / "proposal.md"
    text = "See [charter](../../../docs/CHARTER.md) and [self](./design.md).\n"
    out = arch.rewrite_outbound_links(
        text, old_file=old_file, new_file=new_file, moved_root=old_root
    )
    assert "../../../docs/CHARTER.md" not in out
    assert "../../../../docs/CHARTER.md" in out
    assert "](./design.md)" in out  # intra-tree unchanged

    spec_old = old_root / "specs" / "cap" / "spec.md"
    spec_new = Path("/repo/openspec/changes/archive/foo/specs/cap/spec.md")
    spec_text = "See [adr](../../../../docs/decisions/0005-calibrated-merge-gate.md).\n"
    spec_out = arch.rewrite_outbound_links(
        spec_text, old_file=spec_old, new_file=spec_new, moved_root=old_root
    )
    assert "](../../../../../docs/decisions/0005-calibrated-merge-gate.md)" in spec_out
    assert "](../../../../docs/decisions/0005-calibrated-merge-gate.md)" not in spec_out


def test_http_and_anchor_links_are_left_alone() -> None:
    old_root = Path("/repo/openspec/changes/foo")
    text = "[a](https://example.com/x) [b](#section) [c](mailto:a@b.c)\n"
    out = arch.rewrite_outbound_links(
        text,
        old_file=old_root / "proposal.md",
        new_file=Path("/repo/openspec/changes/archive/foo/proposal.md"),
        moved_root=old_root,
    )
    assert out == text


def test_archive_change_rewrites_and_stamps_status(tmp_path: Path) -> None:
    src = tmp_path / "openspec" / "changes" / "demo"
    src.mkdir(parents=True)
    (src / "proposal.md").write_text(
        "**Status:** proposed · **Date:** 2026-09-06\n\nSee [c](../../../docs/CHARTER.md).\n",
        encoding="utf-8",
    )
    (src / "design.md").write_text("intra\n", encoding="utf-8")
    result = arch.archive_change(tmp_path, "demo", landed="abc1234", git_mv=_mv)
    dest = tmp_path / "openspec" / "changes" / "archive" / "demo" / "proposal.md"
    body = dest.read_text(encoding="utf-8")
    assert "implemented (archived; landed `abc1234`)" in body
    assert "landed `abc1234`) ·" in body
    assert "../../../../docs/CHARTER.md" in body
    assert not (tmp_path / "openspec" / "changes" / "demo").exists()
    assert result.destination.endswith("archive/demo")


def test_cli_missing_change_is_usage_error(tmp_path: Path) -> None:
    assert arch.main(["--repo-root", str(tmp_path), "--change", "nope"]) == 2


def test_slash_in_change_id_is_refused(tmp_path: Path) -> None:
    with pytest.raises(arch.ArchiveError, match="invalid change id"):
        arch.archive_change(tmp_path, "foo/bar", git_mv=_mv)


def test_stamp_status_is_idempotent_enough() -> None:
    text = "**Status:** implemented (archived; landed `old`) · **Date:** x\n"
    assert "`abc`" in arch.stamp_status(text, "abc")
