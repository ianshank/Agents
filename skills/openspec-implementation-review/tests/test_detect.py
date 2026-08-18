"""Unit tests for implreview.detect.

Includes two tests run against the *real* repository tree this skill lives in (not a fixture)
because the whole point of this module is to answer a question about this repo's own,
currently-real state -- see the module docstring and the task brief this skill implements.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from implreview.detect import PLUGIN_ROOT_ENV_VAR, detect_dispatch_path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _make_fake_foundation(repo_root: Path, *, with_charters: bool = True, manifest_name: str = "foundation") -> None:
    agents_dir = repo_root / "claude-foundation" / "agents"
    agents_dir.mkdir(parents=True)
    if with_charters:
        (agents_dir / "spec-guardian.md").write_text("---\nname: spec-guardian\n---\n", encoding="utf-8")
        (agents_dir / "peer-reviewer.md").write_text("---\nname: peer-reviewer\n---\n", encoding="utf-8")
    plugin_dir = repo_root / "claude-foundation" / ".claude-plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text(json.dumps({"name": manifest_name}), encoding="utf-8")


# --- fixture-based: charter presence dominates everything else -----------------------------


def test_missing_charters_forces_degraded_regardless_of_env(tmp_path: Path) -> None:
    _make_fake_foundation(tmp_path, with_charters=False)
    detection = detect_dispatch_path(tmp_path, environ={PLUGIN_ROOT_ENV_VAR: str(tmp_path / "claude-foundation")})
    assert detection.charters_present is False
    assert detection.recommended_path == "degraded"
    assert "not both present" in detection.reason


def test_missing_foundation_dir_entirely_is_degraded(tmp_path: Path) -> None:
    detection = detect_dispatch_path(tmp_path, environ={})
    assert detection.charters_present is False
    assert detection.plugin_manifest_present is False
    assert detection.recommended_path == "degraded"


# --- fixture-based: charters present, env var absent/misdirected ---------------------------


def test_charters_present_but_no_env_var_is_degraded(tmp_path: Path) -> None:
    _make_fake_foundation(tmp_path)
    detection = detect_dispatch_path(tmp_path, environ={})
    assert detection.charters_present is True
    assert detection.plugin_manifest_present is True
    assert detection.claude_plugin_root is None
    assert detection.env_signals_plugin_loaded is False
    assert detection.recommended_path == "degraded"
    assert "unset" in detection.reason


def test_charters_present_env_var_points_elsewhere_is_degraded(tmp_path: Path) -> None:
    _make_fake_foundation(tmp_path)
    other_dir = tmp_path / "somewhere-else"
    other_dir.mkdir()
    detection = detect_dispatch_path(tmp_path, environ={PLUGIN_ROOT_ENV_VAR: str(other_dir)})
    assert detection.env_signals_plugin_loaded is False
    assert detection.recommended_path == "degraded"
    assert str(other_dir) in detection.reason


def test_env_var_pointing_at_a_nonexistent_path_does_not_crash(tmp_path: Path) -> None:
    _make_fake_foundation(tmp_path)
    detection = detect_dispatch_path(tmp_path, environ={PLUGIN_ROOT_ENV_VAR: "/nonexistent/nowhere"})
    assert detection.env_signals_plugin_loaded is False
    assert detection.recommended_path == "degraded"


def test_env_var_pointing_at_a_symlink_loop_does_not_crash(tmp_path: Path) -> None:
    # A real Path.resolve() failure on a self-referencing symlink, not a monkeypatch --
    # exercises _env_signals_plugin_loaded's defensive handling with a genuine failure.
    # Which of its two except clauses fires is platform/Python-version dependent (this
    # sandbox raises RuntimeError: "Symlink loop"; POSIX ELOOP as OSError is also real on
    # other platforms) -- both are caught, and this test asserts the resulting behavior,
    # not which branch ran.
    _make_fake_foundation(tmp_path)
    loop = tmp_path / "self-loop"
    try:
        loop.symlink_to(loop)
    except OSError as exc:
        # Probe, don't assume: non-elevated Windows needs Administrator or Developer Mode
        # to create symlinks at all (WinError 1314). This test's actual target is
        # resolve()'s ELOOP/RuntimeError handling, not symlink creation -- a host that
        # can't build the fixture skips this one test rather than failing the whole suite
        # (AGENTS.md "Windows / cross-platform gotchas": known trap, not a real failure).
        pytest.skip(f"platform cannot create symlinks (fixture setup, not the code under test): {exc!r}")
    detection = detect_dispatch_path(tmp_path, environ={PLUGIN_ROOT_ENV_VAR: str(loop)})
    assert detection.env_signals_plugin_loaded is False
    assert detection.recommended_path == "degraded"


# --- fixture-based: the one case that recommends "plugin" ----------------------------------


def test_env_var_pointing_exactly_at_foundation_dir_recommends_plugin(tmp_path: Path) -> None:
    _make_fake_foundation(tmp_path)
    foundation_dir = tmp_path / "claude-foundation"
    detection = detect_dispatch_path(tmp_path, environ={PLUGIN_ROOT_ENV_VAR: str(foundation_dir)})
    assert detection.env_signals_plugin_loaded is True
    assert detection.recommended_path == "plugin"
    assert detection.confidence == "medium"  # never "high" -- see module docstring
    assert "corroborate" in detection.reason.lower()


def test_env_var_with_relative_dots_still_resolves(tmp_path: Path) -> None:
    _make_fake_foundation(tmp_path)
    # One ".." from agents/ lands back on claude-foundation/ itself.
    indirect = tmp_path / "claude-foundation" / "agents" / ".."
    detection = detect_dispatch_path(tmp_path, environ={PLUGIN_ROOT_ENV_VAR: str(indirect)})
    assert detection.recommended_path == "plugin"


# --- plugin manifest content checks ---------------------------------------------------------


def test_malformed_manifest_json_is_not_present(tmp_path: Path) -> None:
    agents_dir = tmp_path / "claude-foundation" / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "spec-guardian.md").write_text("x", encoding="utf-8")
    (agents_dir / "peer-reviewer.md").write_text("x", encoding="utf-8")
    plugin_dir = tmp_path / "claude-foundation" / ".claude-plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text("{not valid json", encoding="utf-8")
    detection = detect_dispatch_path(tmp_path, environ={})
    assert detection.plugin_manifest_present is False


def test_manifest_with_wrong_name_is_not_present(tmp_path: Path) -> None:
    _make_fake_foundation(tmp_path, manifest_name="something-else")
    detection = detect_dispatch_path(tmp_path, environ={})
    assert detection.plugin_manifest_present is False


# --- against the real repo tree -------------------------------------------------------------


def test_real_repo_charters_exist_and_no_plugin_env_is_degraded() -> None:
    # Preconditions this test documents rather than assumes -- if these ever go false, Phase
    # 4's charters were removed/renamed and this skill's core premise needs revisiting.
    assert (REPO_ROOT / "claude-foundation" / "agents" / "spec-guardian.md").is_file()
    assert (REPO_ROOT / "claude-foundation" / "agents" / "peer-reviewer.md").is_file()

    detection = detect_dispatch_path(REPO_ROOT, environ={})
    assert detection.charters_present is True
    assert detection.recommended_path == "degraded"


def test_real_repo_with_the_actual_process_environment_is_degraded() -> None:
    # Empirically confirmed for this task: no session working this repo directly has
    # CLAUDE_PLUGIN_ROOT pointing at claude-foundation/, because claude-foundation is staged
    # (ADR 0028), not plugin-loaded, in ordinary sessions. Passing environ=None (the default)
    # uses the real os.environ, so this is the live check, not a simulation.
    detection = detect_dispatch_path(REPO_ROOT)
    assert detection.recommended_path == "degraded"
