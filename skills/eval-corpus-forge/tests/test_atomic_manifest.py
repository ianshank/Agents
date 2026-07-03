"""Unit tests for forge.atomic and forge.manifest: writing, swapping, backup restore, counts."""

from __future__ import annotations

import os

import pytest
from forge import atomic, normalize, views
from forge import manifest as manifest_mod


def _pkg_inputs():
    raw = {
        "prompt": "x",
        "expected_outcome": {"a": 1},
        "response": "r",
        "expected_output_fields": {"a": 1},
        "trace": {"tool_names": ["t"], "retrieved_ids": ["d"]},
    }
    canonicals = [normalize.to_canonical(("f", "1", raw))]
    view_data = views.build_views(canonicals)
    return canonicals, view_data


def test_write_package_strips_internal_and_writes_all(tmp_path):
    canonicals, view_data = _pkg_inputs()
    out = str(tmp_path / "pkg")
    os.makedirs(out)
    atomic.write_package(
        out, canonicals=canonicals, ground_truth=[], views=view_data, provenance=[c["provenance"] for c in canonicals]
    )
    scen = (tmp_path / "pkg" / "canonical" / "scenarios.jsonl").read_text(encoding="utf-8")
    assert "_raw" not in scen  # internal field stripped
    for name in views.VIEW_NAMES:
        assert (tmp_path / "pkg" / "views" / f"{name}.jsonl").exists()
    assert (tmp_path / "pkg" / "ground_truth" / "mappings.jsonl").exists()
    assert (tmp_path / "pkg" / "provenance" / "source_index.jsonl").exists()


def test_make_temp_dir_is_sibling_of_out(tmp_path):
    out = str(tmp_path / "final")
    tmp = atomic.make_temp_dir(out)
    assert os.path.dirname(tmp) == os.path.dirname(os.path.abspath(out))
    assert os.path.isdir(tmp)


def test_commit_into_empty_target(tmp_path):
    out = str(tmp_path / "final")
    tmp = atomic.make_temp_dir(out)
    (open(os.path.join(tmp, "marker"), "w")).close()
    backup = atomic.commit(tmp, out)
    assert backup is None
    assert os.path.exists(os.path.join(out, "marker"))


def test_commit_backs_up_existing(tmp_path):
    out = str(tmp_path / "final")
    os.makedirs(out)
    (open(os.path.join(out, "old"), "w")).close()
    tmp = atomic.make_temp_dir(out)
    (open(os.path.join(tmp, "new"), "w")).close()
    backup = atomic.commit(tmp, out)
    assert backup is not None and os.path.exists(os.path.join(backup, "old"))
    assert os.path.exists(os.path.join(out, "new"))


def test_commit_restores_original_when_replace_fails(tmp_path, monkeypatch):
    out = str(tmp_path / "final")
    os.makedirs(out)
    (open(os.path.join(out, "important"), "w")).close()
    tmp = atomic.make_temp_dir(out)

    def boom(*_a, **_k):
        raise OSError("simulated swap failure")

    monkeypatch.setattr(atomic.os, "replace", boom)
    with pytest.raises(OSError, match="simulated"):
        atomic.commit(tmp, out)
    # contract: original is restored at its path
    assert os.path.exists(os.path.join(out, "important"))


def test_commit_restore_path_logs_warning(tmp_path, monkeypatch, caplog):
    out = str(tmp_path / "final")
    os.makedirs(out)
    tmp = atomic.make_temp_dir(out)

    def boom(*_a, **_k):
        raise OSError("simulated swap failure")

    monkeypatch.setattr(atomic.os, "replace", boom)
    with caplog.at_level("WARNING", logger="forge.atomic"), pytest.raises(OSError):
        atomic.commit(tmp, out)
    assert any("restoring previous output" in r.message for r in caplog.records)


def test_make_temp_dir_exhaustion_logs_and_raises(tmp_path, monkeypatch, caplog):
    out = str(tmp_path / "final")

    def always_exists(path, *_a, **_k):
        if ".tmp." in path:
            raise FileExistsError
        # parent-directory creation proceeds as a no-op

    monkeypatch.setattr(atomic.os, "makedirs", always_exists)
    with caplog.at_level("WARNING", logger="forge.atomic"), pytest.raises(OSError, match="unique temp dir"):
        atomic.make_temp_dir(out)
    assert any("exhausted" in r.message for r in caplog.records)


def test_manifest_counts_and_applicability():
    canonicals, view_data = _pkg_inputs()
    m = manifest_mod.build_manifest(
        dataset_name="d",
        source_input="s",
        mode="full_dataset",
        canonical_count=len(canonicals),
        ground_truth_count=1,
        views=view_data,
        validation_status="passed",
    )
    assert m["schema_version"] == manifest_mod.SCHEMA_VERSION
    assert m["counts"]["canonical_scenarios"] == 1
    assert m["counts"]["retrieval_eval_records"] == 1
    assert set(m["view_applicability"]) == set(views.VIEW_NAMES)
    assert m["validation"]["report_path"] == "validation/validation_report.json"
