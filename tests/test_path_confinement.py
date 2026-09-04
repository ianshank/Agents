"""Path-containment tests for the shared ``core._paths`` helper and its two call sites.

Two real defects motivate this file, and each has a named regression test below:

1. **Sibling-prefix bypass (read path).** ``_validate_dataset_path`` confined dataset
   reads with ``str(resolved).startswith(str(data_root))``. A string prefix is not a
   path prefix, so ``DATA_ROOT=/srv/data`` accepted ``/srv/data-secrets/leak.jsonl``.
   The fix is ``Path.is_relative_to``.
2. **Traversal check disabled by DATA_ROOT (read path).** The ``..`` guard was suffixed
   with ``and not data_root_env``, so opting into confinement switched the other guard
   off. Confinement must be strictly stronger with a root set, never weaker.

The sinks had no validation at all: any config could create and overwrite a file
anywhere the process could write. They now go through the same helper against a
*separate* write root (``OUTPUT_ROOT``), so a read-only corpus directory is never
made writable by being named as the read root.

Everything here is offline and deterministic: ``resolve_confined_path`` touches the
filesystem only through ``Path.resolve``, and the ``/srv/...`` paths are never opened.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest

from eval_harness.core._paths import DATA_ROOT_ENV, OUTPUT_ROOT_ENV, resolve_confined_path
from eval_harness.core.types import (
    EvalItem,
    ItemResult,
    RunResult,
    ScoreAggregate,
    ScoreResult,
    TargetOutput,
)
from eval_harness.datasets import _validate_dataset_path
from eval_harness.sinks import HtmlFileSink, JsonFileSink, _validate_output_path


@pytest.fixture(autouse=True)
def _no_inherited_roots(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralise any root inherited from the developer's shell.

    Surgical ``delenv`` rather than ``os.environ.clear()`` (AGENTS.md "Testing
    conventions"); each test opts back in to the root it needs.
    """
    monkeypatch.delenv(DATA_ROOT_ENV, raising=False)
    monkeypatch.delenv(OUTPUT_ROOT_ENV, raising=False)


def _run() -> RunResult:
    """A minimal, fully deterministic ``RunResult`` for the file sinks to emit."""
    item = EvalItem(id="i", inputs={}, expected=None)
    ir = ItemResult(item=item, output=TargetOutput(output="o"), scores=[ScoreResult("acc", 1.0, True)])
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return RunResult(
        run_id="r1",
        config_name="c",
        items=[ir],
        aggregate={"acc": ScoreAggregate(count=1, mean=1.0, pass_rate=1.0)},
        started_at=now,
        finished_at=now,
    )


# ---------------------------------------------------------------------------
# The helper itself
# ---------------------------------------------------------------------------


class TestResolveConfinedPath:
    """Direct unit tests for the shared helper both call sites delegate to."""

    def test_env_var_names_are_distinct(self) -> None:
        """The read root and the write root must never be the same variable."""
        assert DATA_ROOT_ENV != OUTPUT_ROOT_ENV

    def test_unset_root_returns_resolved_path(self, tmp_path: Path) -> None:
        target = tmp_path / "sub" / "f.json"
        assert resolve_confined_path(target, root_env_var=OUTPUT_ROOT_ENV) == target.resolve()

    def test_blank_root_is_treated_as_unset(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """An empty/whitespace value must not confine to the process CWD."""
        monkeypatch.setenv(OUTPUT_ROOT_ENV, "   ")
        target = tmp_path / "f.json"
        assert resolve_confined_path(target, root_env_var=OUTPUT_ROOT_ENV) == target.resolve()

    def test_must_exist_rejects_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="does not exist"):
            resolve_confined_path(tmp_path / "absent.jsonl", root_env_var=DATA_ROOT_ENV, must_exist=True)

    def test_must_exist_accepts_existing_file(self, tmp_path: Path) -> None:
        present = tmp_path / "present.jsonl"
        present.write_text("{}\n", encoding="utf-8")
        assert resolve_confined_path(present, root_env_var=DATA_ROOT_ENV, must_exist=True) == present.resolve()

    def test_write_path_allows_missing_file_and_missing_parent(self, tmp_path: Path) -> None:
        """The write path must validate a file whose parent will be created later."""
        target = tmp_path / "not" / "yet" / "there.json"
        assert resolve_confined_path(target, root_env_var=OUTPUT_ROOT_ENV) == target.resolve()
        assert not target.parent.exists()

    def test_description_appears_in_containment_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(OUTPUT_ROOT_ENV, str(tmp_path / "root"))
        with pytest.raises(ValueError, match=r"Widget path .* is outside"):
            resolve_confined_path(tmp_path / "elsewhere.json", root_env_var=OUTPUT_ROOT_ENV, description="widget path")

    def test_warning_suppressed_when_absolute_is_expected(self, tmp_path: Path, caplog) -> None:
        with caplog.at_level(logging.WARNING):
            resolve_confined_path(tmp_path / "f.json", root_env_var=DATA_ROOT_ENV, warn_unconfined_absolute=False)
        assert caplog.text == ""


# ---------------------------------------------------------------------------
# Read path — datasets
# ---------------------------------------------------------------------------


class TestDatasetPathConfinement:
    def test_sibling_prefix_directory_is_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Regression: ``DATA_ROOT=/srv/data`` must reject ``/srv/data-secrets/leak.jsonl``.

        The old string-prefix test accepted it because the sibling directory's name
        starts with the root's name. No filesystem access: neither path is opened.
        """
        monkeypatch.setenv(DATA_ROOT_ENV, "/srv/data")
        with pytest.raises(ValueError, match="outside DATA_ROOT"):
            _validate_dataset_path("/srv/data-secrets/leak.jsonl")

    def test_sibling_prefix_file_is_rejected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The same bypass on a real tmp_path tree, in case ``/srv`` ever exists."""
        root = tmp_path / "data"
        root.mkdir()
        sibling = tmp_path / "data-secrets"
        sibling.mkdir()
        leak = sibling / "leak.jsonl"
        leak.write_text("{}\n", encoding="utf-8")

        monkeypatch.setenv(DATA_ROOT_ENV, str(root))
        with pytest.raises(ValueError, match="outside DATA_ROOT"):
            _validate_dataset_path(str(leak))

    def test_traversal_still_rejected_with_data_root_set(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Regression: setting DATA_ROOT used to switch the ``..`` guard off."""
        root = tmp_path / "data"
        root.mkdir()
        monkeypatch.setenv(DATA_ROOT_ENV, str(root))
        with pytest.raises(ValueError, match="Path traversal"):
            _validate_dataset_path(f"{root}/../../etc/passwd")

    def test_traversal_inside_root_rejected_with_data_root_set(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Even a ``..`` that resolves back inside the root is rejected, not normalised away."""
        root = tmp_path / "data"
        (root / "sub").mkdir(parents=True)
        monkeypatch.setenv(DATA_ROOT_ENV, str(root))
        with pytest.raises(ValueError, match="Path traversal"):
            _validate_dataset_path(f"{root}/sub/../inside.jsonl")

    def test_legitimate_path_inside_data_root_accepted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        root = tmp_path / "data"
        (root / "nested").mkdir(parents=True)
        target = root / "nested" / "items.jsonl"
        target.write_text('{"id": "a"}\n', encoding="utf-8")

        monkeypatch.setenv(DATA_ROOT_ENV, str(root))
        assert _validate_dataset_path(str(target)) == target.resolve()

    def test_data_root_itself_is_accepted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """``is_relative_to`` treats the root as contained in itself; keep that."""
        root = tmp_path / "data"
        root.mkdir()
        monkeypatch.setenv(DATA_ROOT_ENV, str(root))
        assert _validate_dataset_path(str(root)) == root.resolve()

    def test_allow_absolute_suppresses_the_warning(self, tmp_path: Path, caplog) -> None:
        with caplog.at_level(logging.WARNING):
            _validate_dataset_path(str(tmp_path / "d.jsonl"), allow_absolute=True)
        assert caplog.text == ""


# ---------------------------------------------------------------------------
# Write path — sinks
# ---------------------------------------------------------------------------


class TestSinkOutputConfinement:
    def test_json_sink_rejects_path_outside_output_root(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        root = tmp_path / "reports"
        root.mkdir()
        monkeypatch.setenv(OUTPUT_ROOT_ENV, str(root))
        with pytest.raises(ValueError, match=f"outside {OUTPUT_ROOT_ENV}"):
            JsonFileSink(path=str(tmp_path / "escape.json"))

    def test_json_sink_rejects_sibling_prefix_directory(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The read path's sibling-prefix bypass must not exist on the write path either."""
        root = tmp_path / "reports"
        root.mkdir()
        monkeypatch.setenv(OUTPUT_ROOT_ENV, str(root))
        with pytest.raises(ValueError, match=f"outside {OUTPUT_ROOT_ENV}"):
            JsonFileSink(path=str(tmp_path / "reports-private" / "leak.json"))

    def test_html_sink_rejects_path_outside_output_root(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        root = tmp_path / "reports"
        root.mkdir()
        monkeypatch.setenv(OUTPUT_ROOT_ENV, str(root))
        with pytest.raises(ValueError, match=f"outside {OUTPUT_ROOT_ENV}"):
            HtmlFileSink(path=str(tmp_path / "escape.html"))

    def test_sink_rejects_traversal_out_of_output_root(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        root = tmp_path / "reports"
        root.mkdir()
        monkeypatch.setenv(OUTPUT_ROOT_ENV, str(root))
        with pytest.raises(ValueError, match="Path traversal"):
            JsonFileSink(path=f"{root}/../escape.json")

    def test_json_sink_writes_inside_output_root(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        root = tmp_path / "reports"
        root.mkdir()
        monkeypatch.setenv(OUTPUT_ROOT_ENV, str(root))
        sink = JsonFileSink(path=str(root / "results.json"))
        sink.emit(_run())
        assert json.loads((root / "results.json").read_text())["run_id"] == "r1"

    def test_html_sink_writes_inside_output_root(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        root = tmp_path / "reports"
        root.mkdir()
        monkeypatch.setenv(OUTPUT_ROOT_ENV, str(root))
        sink = HtmlFileSink(path=str(root / "report.html"))
        sink.emit(_run())
        assert "<html" in (root / "report.html").read_text().lower()

    def test_sink_creates_missing_nested_directory_inside_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A not-yet-existing nested directory under the root is still created on emit."""
        root = tmp_path / "reports"
        root.mkdir()
        monkeypatch.setenv(OUTPUT_ROOT_ENV, str(root))
        target = root / "2026" / "run-1" / "results.json"
        sink = JsonFileSink(path=str(target))
        assert not target.parent.exists()
        sink.emit(_run())
        assert json.loads(target.read_text())["run_id"] == "r1"

    def test_unrestricted_write_with_warning_when_root_unset(self, tmp_path: Path, caplog) -> None:
        """Backwards compatibility: no root means no restriction, but one warning."""
        target = tmp_path / "anywhere" / "results.json"
        with caplog.at_level(logging.WARNING):
            sink = JsonFileSink(path=str(target))
        assert sink.path == target.resolve()
        assert OUTPUT_ROOT_ENV in caplog.text
        assert "without" in caplog.text

        caplog.clear()
        sink.emit(_run())
        assert json.loads(target.read_text())["run_id"] == "r1"
        assert caplog.text == "", "the warning belongs to construction, not to every emit"

    def test_relative_output_path_does_not_warn(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog) -> None:
        """A relative path is CWD-scoped already; today's default configs must stay quiet."""
        monkeypatch.chdir(tmp_path)
        with caplog.at_level(logging.WARNING):
            sink = JsonFileSink(path="out/results.json")
        assert sink.path == (tmp_path / "out" / "results.json").resolve()
        assert caplog.text == ""

    def test_validate_output_path_is_the_shared_helper(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(OUTPUT_ROOT_ENV, str(tmp_path))
        assert _validate_output_path(str(tmp_path / "a.json")) == (tmp_path / "a.json").resolve()


# ---------------------------------------------------------------------------
# Symlinks: the case containment exists for, and the one nothing was holding
# ---------------------------------------------------------------------------


def _can_symlink(tmp_path: Path) -> bool:
    """Windows needs SeCreateSymbolicLinkPrivilege; skip rather than fail there."""
    try:
        (tmp_path / "_probe_link").symlink_to(tmp_path)
    except (OSError, NotImplementedError):
        return False
    (tmp_path / "_probe_link").unlink()
    return True


class TestSymlinkConfinement:
    """Containment rests entirely on ``Path.resolve`` following symlinks.

    That is correct today and was completely untested: a directory inside the
    root symlinked out is the textbook escape, and nothing in the suite pinned
    it. These tests exist so a future refactor to ``resolve(strict=False)``
    semantics, or a switch to a non-resolving comparison, cannot pass silently.
    """

    @pytest.fixture(autouse=True)
    def _require_symlinks(self, tmp_path: Path) -> None:
        if not _can_symlink(tmp_path):
            pytest.skip("symlink creation not permitted on this platform")

    @staticmethod
    def _root_and_outside(tmp_path: Path) -> tuple[Path, Path]:
        root = tmp_path / "root"
        outside = tmp_path / "outside"
        root.mkdir()
        outside.mkdir()
        return root, outside

    def test_directory_symlink_escaping_the_root_is_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root, outside = self._root_and_outside(tmp_path)
        (outside / "secret.jsonl").write_text("{}\n", encoding="utf-8")
        (root / "link").symlink_to(outside, target_is_directory=True)
        monkeypatch.setenv(DATA_ROOT_ENV, str(root))

        with pytest.raises(ValueError, match="outside"):
            _validate_dataset_path(root / "link" / "secret.jsonl", allow_absolute=True)

    def test_file_symlink_escaping_the_root_is_rejected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        root, outside = self._root_and_outside(tmp_path)
        real = outside / "secret.jsonl"
        real.write_text("{}\n", encoding="utf-8")
        (root / "alias.jsonl").symlink_to(real)
        monkeypatch.setenv(DATA_ROOT_ENV, str(root))

        with pytest.raises(ValueError, match="outside"):
            _validate_dataset_path(root / "alias.jsonl", allow_absolute=True)

    def test_a_root_that_is_itself_a_symlink_still_admits_its_contents(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Deny-by-accident would be as bad as allow-by-accident: a root given
        via a symlinked path (a very common deployment shape) must still work."""
        real_root, _ = self._root_and_outside(tmp_path)
        (real_root / "data.jsonl").write_text("{}\n", encoding="utf-8")
        linked_root = tmp_path / "root-link"
        linked_root.symlink_to(real_root, target_is_directory=True)
        monkeypatch.setenv(DATA_ROOT_ENV, str(linked_root))

        resolved = _validate_dataset_path(linked_root / "data.jsonl", allow_absolute=True)

        assert resolved == (real_root / "data.jsonl").resolve()

    def test_a_sink_cannot_write_through_a_symlinked_parent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root, outside = self._root_and_outside(tmp_path)
        (root / "reports").symlink_to(outside, target_is_directory=True)
        monkeypatch.setenv(OUTPUT_ROOT_ENV, str(root))

        with pytest.raises(ValueError, match="outside"):
            JsonFileSink(path=str(root / "reports" / "out.json"))
