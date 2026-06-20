from __future__ import annotations

import json

import pytest

from behavioral_regression import cli


def test_coerce_types():
    assert cli._coerce("true") is True
    assert cli._coerce("false") is False
    assert cli._coerce("42") == 42
    assert cli._coerce("0.5") == 0.5
    assert cli._coerce("hello") == "hello"


def test_build_config_applies_overrides():
    cfg = cli._build_config(["v2_sycophancy_mean=0.55", "n_pairs=50"])
    assert cfg.v2_sycophancy_mean == 0.55
    assert cfg.n_pairs == 50


def test_build_config_rejects_bad_override():
    with pytest.raises(ValueError, match="key=value"):
        cli._build_config(["noequals"])


def test_build_config_unknown_key_raises_config_error():
    from behavioral_regression.config import ConfigError

    with pytest.raises(ConfigError, match="unknown config keys"):
        cli._build_config(["bogus_field=1"])


def test_main_writes_json_and_html(tmp_path):
    out = tmp_path / "r.json"
    html = tmp_path / "r.html"
    rc = cli.main(["--seed", "7", "--set", "n_pairs=120", "--out", str(out), "--html", str(html)])
    assert rc == 0
    payload = json.loads(out.read_text())
    assert payload["decision"] in {"ship", "hold", "escalate"}
    assert "<svg" in html.read_text()


def test_main_prints_to_stdout(capsys):
    rc = cli.main(["--seed", "7", "--set", "n_pairs=80"])
    assert rc == 0
    out = capsys.readouterr().out
    assert json.loads(out)["decision"] in {"ship", "hold", "escalate"}
