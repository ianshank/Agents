"""Unit tests for deterministic deploy-script rendering (``deploygen.render``)."""

from __future__ import annotations

from deploygen import DeployConfig, render_deploy


def test_header_strict_mode_and_shape() -> None:
    out = render_deploy(DeployConfig())
    assert out.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in out
    assert out.endswith("\n") and not out.endswith("\n\n")


def test_all_safety_rails_present() -> None:
    out = render_deploy(DeployConfig())
    for token in (
        "run()",
        "confirm()",
        "require()",
        "do_build()",
        "do_release()",
        "do_rollback()",
        "do_health_check()",
        "usage()",
        'main "$@"',
        "--dry-run)",
        "DRY-RUN:",
    ):
        assert token in out, token


def test_config_values_land_as_overridable_defaults() -> None:
    out = render_deploy(
        DeployConfig(app="mysvc", environment="staging", artifact="reg/mysvc:9", health_url="https://h/z")
    )
    assert 'APP="${APP:-mysvc}"' in out
    assert 'ENVIRONMENT="${ENVIRONMENT:-staging}"' in out
    assert 'ARTIFACT="${ARTIFACT:-reg/mysvc:9}"' in out
    assert 'HEALTH_URL="${HEALTH_URL:-https://h/z}"' in out


def test_no_inlined_secrets_every_value_is_env_overridable() -> None:
    # ADR-0009 baseline: config comes from the environment; nothing is hard-coded.
    out = render_deploy(DeployConfig(app="svc"))
    for var in ("APP", "ENVIRONMENT", "ARTIFACT", "HEALTH_URL"):
        assert f'{var}="${{{var}:-' in out


def test_variable_expansions_are_quoted() -> None:
    out = render_deploy(DeployConfig())
    assert '"$ARTIFACT"' in out
    assert '"$HEALTH_URL"' in out
    assert '"$@"' in out


def test_deterministic() -> None:
    cfg = DeployConfig(app="a", artifact="r:1")
    assert render_deploy(cfg) == render_deploy(cfg)
