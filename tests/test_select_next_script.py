#!/usr/bin/env python3
"""Tests for scripts/select_next.py — DAG-aware next-feature selection."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import select_next as sn
import yaml

# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def test_load_features_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "features.yaml"
    p.write_text(yaml.safe_dump({"features": [{"id": "F-001"}]}), encoding="utf-8")
    assert sn._load_features(p) == [{"id": "F-001"}]


@pytest.mark.parametrize(
    "payload",
    ["- a\n- list\n", "no_features: true\n", "features: not-a-list\n"],
)
def test_load_features_rejects_bad_shapes(tmp_path: Path, payload: str) -> None:
    p = tmp_path / "features.yaml"
    p.write_text(payload, encoding="utf-8")
    with pytest.raises(ValueError, match="features"):
        sn._load_features(p)


# ---------------------------------------------------------------------------
# Selection logic
# ---------------------------------------------------------------------------


def _feat(fid: str, **kw: Any) -> dict[str, Any]:
    return {"id": fid, "name": fid, "status": "todo", **kw}


def test_priority_key_known_and_unknown() -> None:
    assert sn._priority_key({"priority": "critical"}) == 0
    assert sn._priority_key({}) == sn.PRIORITY_ORDER["low"]
    assert sn._priority_key({"priority": "bogus"}) == 99


def test_in_progress_resumes_first_by_priority() -> None:
    feats = [
        _feat("F-1", status="in_progress", priority="low"),
        _feat("F-2", status="in_progress", priority="critical"),
        _feat("F-3", priority="critical"),
    ]
    selected = sn.select_next(feats)
    assert selected is not None and selected["id"] == "F-2"


def test_ready_todo_picked_by_priority() -> None:
    feats = [
        _feat("F-1", status="done"),
        _feat("F-2", priority="medium", depends_on=["F-1"]),
        _feat("F-3", priority="high", depends_on=["F-1"]),
        _feat("F-4", priority="critical", depends_on=["F-404"]),  # blocked
    ]
    selected = sn.select_next(feats)
    assert selected is not None and selected["id"] == "F-3"


def test_all_blocked_returns_none() -> None:
    feats = [_feat("F-1", depends_on=["F-2"]), _feat("F-2", depends_on=["F-1"])]
    assert sn.select_next(feats) is None


def test_nothing_remaining_returns_none() -> None:
    assert sn.select_next([_feat("F-1", status="done")]) is None
    assert sn.select_next([]) is None


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------


def test_main_missing_file(tmp_path: Path) -> None:
    assert sn.main(["--features", str(tmp_path / "absent.yaml")]) == 2


def test_main_invalid_file(tmp_path: Path) -> None:
    p = tmp_path / "features.yaml"
    p.write_text("just a scalar\n", encoding="utf-8")
    assert sn.main(["--features", str(p)]) == 2


def test_main_prints_selected_id(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    p = tmp_path / "features.yaml"
    p.write_text(
        yaml.safe_dump({"features": [_feat("F-7", priority="high")]}),
        encoding="utf-8",
    )
    assert sn.main(["--features", str(p)]) == 0
    assert capsys.readouterr().out.strip() == "F-7"


def test_main_all_blocked_exits_2(tmp_path: Path) -> None:
    p = tmp_path / "features.yaml"
    p.write_text(
        yaml.safe_dump({"features": [_feat("F-1", depends_on=["F-404"])]}),
        encoding="utf-8",
    )
    assert sn.main(["--features", str(p)]) == 2
