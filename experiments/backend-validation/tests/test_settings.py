"""Unit tests for typed settings: interpolation, overrides, containment, env-name hygiene."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend_validation.settings import (
    BackendSpec,
    Settings,
    SettingsError,
    apply_overrides,
    interpolate,
    load_settings,
)

SUBTREE = Path(__file__).resolve().parents[1]


def _minimal(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "backends": [
            {
                "id": "langfuse",
                "display_name": "Langfuse",
                "base_url": "http://127.0.0.1:18321",
                "compose_file": "deploy/langfuse/compose.yaml",
                "sdk_extra": "langfuse",
                "credential_env": {"secret_key": "BV_LANGFUSE_SECRET_KEY"},
            }
        ],
        "judge": {"base_url": "http://127.0.0.1:18323/v1", "model": "m", "api_key_env": "BV_JUDGE_API_KEY"},
        "timeouts": {"op_seconds": 30, "probe_budget_seconds": 300},
        "retries": {"max_attempts": 3, "backoff_base_seconds": 2},
        "artifacts_dir": "artifacts",
        "reports_dir": "reports",
        "min_free_gb": 20,
        "control_endpoint": "http://127.0.0.1:1/",
    }
    data.update(overrides)
    return data


# ------------------------------------------------------------------ interpolation
def test_interpolate_env_and_default() -> None:
    env = {"PORT": "9999"}
    assert interpolate("http://x:${PORT}", env) == "http://x:9999"
    assert interpolate("http://x:${MISSING:-18321}", env) == "http://x:18321"
    assert interpolate(["${PORT}", {"k": "${MISSING:-d}"}], env) == ["9999", {"k": "d"}]
    assert interpolate(42, env) == 42


def test_interpolate_missing_without_default_is_error() -> None:
    with pytest.raises(SettingsError, match="MISSING"):
        interpolate("${MISSING}", {})


def test_interpolate_empty_default_is_allowed() -> None:
    assert interpolate("${MISSING:-}", {}) == ""


# --------------------------------------------------------------------- overrides
def test_apply_overrides_replaces_nested_value() -> None:
    data = {"timeouts": {"op_seconds": 30}}
    assert apply_overrides(data, ["timeouts.op_seconds=5"])["timeouts"]["op_seconds"] == 5


def test_apply_overrides_rejects_unknown_path_and_bad_shape() -> None:
    with pytest.raises(SettingsError, match="does not exist"):
        apply_overrides({"a": {}}, ["a.b.c=1"])
    with pytest.raises(SettingsError, match="does not exist"):
        apply_overrides({"a": {}}, ["a.missing=1"])
    with pytest.raises(SettingsError, match=r"key\.path=value"):
        apply_overrides({"a": {}}, ["nonsense"])


# ----------------------------------------------------------------------- models
def test_backend_lookup_and_unknown_backend() -> None:
    settings = Settings.model_validate(_minimal())
    assert settings.backend("langfuse").sdk_extra == "langfuse"
    with pytest.raises(SettingsError, match="unknown backend"):
        settings.backend("mlflow")


def test_credential_env_must_be_env_var_names() -> None:
    with pytest.raises(ValueError, match="ENV VAR NAME"):
        BackendSpec(
            id="x",
            display_name="X",
            base_url="http://x",
            compose_file="deploy/x/compose.yaml",
            sdk_extra="x",
            credential_env={"secret": "sk-lf-not-a-name"},
        )


def test_backend_id_must_be_slug() -> None:
    with pytest.raises(ValueError, match="lowercase slug"):
        BackendSpec(
            id="Bad Id",
            display_name="X",
            base_url="http://x",
            compose_file="deploy/x/compose.yaml",
            sdk_extra="x",
        )


def test_resolve_dir_containment(tmp_path: Path) -> None:
    settings = Settings.model_validate(_minimal())
    resolved = settings.resolve_dir("artifacts_dir", tmp_path)
    assert resolved == (tmp_path / "artifacts").resolve()
    escaping = Settings.model_validate(_minimal(artifacts_dir="../outside"))
    with pytest.raises(SettingsError, match="escapes the experiment subtree"):
        escaping.resolve_dir("artifacts_dir", tmp_path)


# ----------------------------------------------------------------------- loader
def test_load_settings_reads_the_committed_config_with_defaults() -> None:
    settings = load_settings(SUBTREE / "config.yaml", env={})
    ids = [spec.id for spec in settings.backends]
    assert ids == ["langfuse", "opik"]
    assert settings.backend("langfuse").base_url.endswith(":18321")
    assert settings.timeouts.op_seconds == 30.0
    assert settings.required_ports == [18321, 18322, 18323]
    # Secrets are env-var NAMES here, never values.
    assert settings.backend("opik").credential_env == {"api_key": "BV_OPIK_API_KEY"}


def test_load_settings_env_and_override_precedence(tmp_path: Path) -> None:
    settings = load_settings(
        SUBTREE / "config.yaml",
        env={"BV_LANGFUSE_PORT": "28321"},
        overrides=["timeouts.op_seconds=7"],
    )
    assert settings.backend("langfuse").base_url.endswith(":28321")
    assert settings.timeouts.op_seconds == 7.0


def test_load_settings_error_paths(tmp_path: Path) -> None:
    with pytest.raises(SettingsError, match="cannot read"):
        load_settings(tmp_path / "missing.yaml", env={})
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text("a: [unclosed", encoding="utf-8")
    with pytest.raises(SettingsError, match="not valid YAML"):
        load_settings(bad_yaml, env={})
    scalar = tmp_path / "scalar.yaml"
    scalar.write_text("42\n", encoding="utf-8")
    with pytest.raises(SettingsError, match="mapping at the top level"):
        load_settings(scalar, env={})
    invalid = tmp_path / "invalid.yaml"
    invalid.write_text("backends: []\n", encoding="utf-8")
    with pytest.raises(SettingsError, match="failed validation"):
        load_settings(invalid, env={})
