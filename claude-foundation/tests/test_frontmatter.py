from __future__ import annotations

from pathlib import Path

import pytest

from foundation_tools.frontmatter import FrontmatterError, load_frontmatter, split_frontmatter


def test_split_roundtrip() -> None:
    front, body = split_frontmatter("---\nname: x\ndescription: y\n---\n\nBody text\n")
    assert front == {"name": "x", "description": "y"}
    assert body.strip() == "Body text"


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ("no marker at all\n", "missing leading"),
        ("---\nname: x\n", "unterminated"),
        ("---\n- a\n- b\n---\nbody", "must be a YAML mapping"),
        ("---\nname: [unclosed\n---\nbody", "not valid YAML"),
    ],
)
def test_split_rejects_malformed(text: str, match: str) -> None:
    with pytest.raises(FrontmatterError, match=match):
        split_frontmatter(text)


def test_load_from_path(tmp_path: Path) -> None:
    path = tmp_path / "SKILL.md"
    path.write_text("---\nname: hello\ndescription: hi\n---\nbody\n", encoding="utf-8")
    front, body = load_frontmatter(path)
    assert front["name"] == "hello" and body.strip() == "body"
