#!/usr/bin/env python3
"""Tests for scripts/agent_confidence.py — agent identity + confidence proxy (F-042, ADR 0023)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import agent_confidence as ac
import pytest
import yaml
from check_protected_changes import ConfigError

_ROOT = Path(ac.__file__).resolve().parent.parent

_IDENTITY = {
    "schema_version": "1.0.0",
    "agents": [
        {"agent_version": "claude-code", "branch_prefixes": ["claude/"], "author_logins": []},
        {
            "agent_version": "devin",
            "branch_prefixes": ["devin/"],
            "author_logins": ["devin-ai-integration[bot]"],
        },
    ],
}

_PROXY = {
    "schema_version": "1.0.0",
    "proxy": {
        "base": 1.5,
        "w_size": 2.0,
        "w_files": 1.0,
        "w_tests": 1.0,
        "w_protected": 2.0,
        "size_scale": 400.0,
        "size_cap": 3.0,
        "files_scale": 20.0,
        "files_cap": 3.0,
        "clamp_lo": 0.02,
        "clamp_hi": 0.98,
    },
    "test_globs": ["tests/**", "**/test_*.py"],
}


def _write(tmp_path: Path, name: str, doc: object) -> str:
    p = tmp_path / name
    p.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return str(p)


def _proxy_cfg(tmp_path: Path, **overrides: object) -> ac.ProxyConfig:
    doc = copy.deepcopy(_PROXY)
    doc["proxy"].update(overrides)  # type: ignore[attr-defined]
    return ac.ProxyConfig.load(_write(tmp_path, "proxy.yaml", doc))


# --- identity: load + validation --------------------------------------------
def test_identity_load_valid(tmp_path):
    ident = ac.AgentIdentity.load(_write(tmp_path, "id.yaml", _IDENTITY))
    assert ident.agents[0] == ac.AgentRule("claude-code", ("claude/",), ())
    assert ident.agents[1].author_logins == ("devin-ai-integration[bot]",)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(extra=1),
        lambda d: d.pop("agents"),
        lambda d: d.update(schema_version="9.0.0"),
        lambda d: d.update(agents="nope"),
        lambda d: d.update(agents=[]),
        lambda d: d.update(agents=[{"agent_version": "x", "branch_prefixes": ["x/"]}]),  # missing key
        lambda d: d.update(agents=[{"agent_version": "x", "branch_prefixes": ["x/"], "author_logins": [], "z": 1}]),
        lambda d: d.update(agents=[{"agent_version": "", "branch_prefixes": ["x/"], "author_logins": []}]),
        lambda d: d.update(
            agents=[
                {"agent_version": "dup", "branch_prefixes": ["a/"], "author_logins": []},
                {"agent_version": "dup", "branch_prefixes": ["b/"], "author_logins": []},
            ]
        ),
        lambda d: d.update(agents=[{"agent_version": "x", "branch_prefixes": [123], "author_logins": []}]),
        lambda d: d.update(agents=[{"agent_version": "x", "branch_prefixes": [], "author_logins": []}]),
    ],
)
def test_identity_load_rejects_invalid(tmp_path, mutate):
    doc = copy.deepcopy(_IDENTITY)
    mutate(doc)
    with pytest.raises(ConfigError):
        ac.AgentIdentity.load(_write(tmp_path, "id.yaml", doc))


def test_identity_load_unreadable(tmp_path):
    with pytest.raises(ConfigError):
        ac.AgentIdentity.load(str(tmp_path / "missing.yaml"))


def test_identity_load_not_mapping(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("- just\n- a list\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        ac.AgentIdentity.load(str(p))


# --- identity: resolve ------------------------------------------------------
@pytest.mark.parametrize(
    "head_ref,login,expected",
    [
        ("claude/foo-bar", "ianshank", "claude-code"),  # prefix wins, login ignored
        ("devin/x", "", "devin"),
        ("", "devin-ai-integration[bot]", "devin"),  # login match when no ref
        ("feat/x", "ianshank", None),  # human
        ("fix/y", "", None),
        ("", "", None),
    ],
)
def test_identity_resolve(tmp_path, head_ref, login, expected):
    ident = ac.AgentIdentity.load(_write(tmp_path, "id.yaml", _IDENTITY))
    assert ident.resolve(head_ref, login) == expected


# --- proxy: load + validation -----------------------------------------------
def test_proxy_load_valid(tmp_path):
    cfg = _proxy_cfg(tmp_path)
    assert cfg.base == 1.5
    assert cfg.test_globs == ("tests/**", "**/test_*.py")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(extra=1),
        lambda d: d.update(schema_version="2.0.0"),
        lambda d: d.update(proxy="nope"),
        lambda d: d["proxy"].pop("base"),
        lambda d: d["proxy"].update(surprise=1),
        lambda d: d["proxy"].update(base="not-a-number"),
        lambda d: d["proxy"].update(size_scale=0),
        lambda d: d["proxy"].update(files_scale=-1),
        lambda d: d["proxy"].update(clamp_lo=0.0),  # must be > 0
        lambda d: d["proxy"].update(clamp_lo=0.9, clamp_hi=0.9),  # lo < hi
        lambda d: d["proxy"].update(clamp_hi=1.0),  # must be < 1
        lambda d: d.update(test_globs=[]),
        lambda d: d.update(test_globs=[123]),
    ],
)
def test_proxy_load_rejects_invalid(tmp_path, mutate):
    doc = copy.deepcopy(_PROXY)
    mutate(doc)
    with pytest.raises(ConfigError):
        ac.ProxyConfig.load(_write(tmp_path, "proxy.yaml", doc))


# --- proxy: compute_confidence ----------------------------------------------
def test_confidence_deterministic(tmp_path):
    cfg = _proxy_cfg(tmp_path)
    a = ac.compute_confidence(["src/a.py", "tests/test_a.py"], 120, cfg)
    b = ac.compute_confidence(["src/a.py", "tests/test_a.py"], 120, cfg)
    assert a == b


def test_confidence_strictly_inside_unit_interval(tmp_path):
    cfg = _proxy_cfg(tmp_path)
    for files, lines in [(["a.py"], 1), ([f"s/{i}.py" for i in range(40)], 9000), (["tests/test_x.py"], 30)]:
        c = ac.compute_confidence(files, lines, cfg)
        assert 0.0 < c < 1.0
        assert cfg.clamp_lo <= c <= cfg.clamp_hi


def test_confidence_varies_with_inputs(tmp_path):
    cfg = _proxy_cfg(tmp_path)
    small = ac.compute_confidence(["src/a.py"], 20, cfg)
    big = ac.compute_confidence([f"src/{i}.py" for i in range(30)], 4000, cfg)
    assert small != big


def test_confidence_monotonic_in_size(tmp_path):
    cfg = _proxy_cfg(tmp_path)
    small = ac.compute_confidence(["src/a.py"], 10, cfg)
    large = ac.compute_confidence(["src/a.py"], 2500, cfg)
    assert large < small


def test_confidence_tests_raise_it(tmp_path, monkeypatch):
    # Isolate the test-ratio signal: many test dirs (tests/**) are also protected
    # paths in this repo, so hold touches_protected fixed to compare cleanly.
    cfg = _proxy_cfg(tmp_path)
    monkeypatch.setattr(ac, "matched_protected", lambda files: False)
    with_tests = ac.compute_confidence(["pkg/a.py", "pkg/test_a.py"], 100, cfg)
    without = ac.compute_confidence(["pkg/a.py", "pkg/b.py"], 100, cfg)
    assert with_tests > without


def test_confidence_protected_lowers_it(tmp_path, monkeypatch):
    cfg = _proxy_cfg(tmp_path)
    monkeypatch.setattr(ac, "matched_protected", lambda files: False)
    clean = ac.compute_confidence(["x/a.py"], 100, cfg)
    monkeypatch.setattr(ac, "matched_protected", lambda files: True)
    protected = ac.compute_confidence(["x/a.py"], 100, cfg)
    assert protected < clean


def test_confidence_large_change_clamps_to_floor(tmp_path, monkeypatch):
    cfg = _proxy_cfg(tmp_path)
    monkeypatch.setattr(ac, "matched_protected", lambda files: True)
    c = ac.compute_confidence([f"s/{i}.py" for i in range(50)], 9000, cfg)
    assert c == cfg.clamp_lo


def test_confidence_clamps_to_ceiling(tmp_path, monkeypatch):
    cfg = _proxy_cfg(tmp_path, base=12.0)  # forces sigmoid ~ 1.0
    monkeypatch.setattr(ac, "matched_protected", lambda files: False)
    c = ac.compute_confidence(["tests/test_a.py"], 1, cfg)
    assert c == cfg.clamp_hi


def test_confidence_empty_change(tmp_path):
    cfg = _proxy_cfg(tmp_path)
    c = ac.compute_confidence([], 0, cfg)
    assert 0.0 < c < 1.0


# --- committed configs are valid + wired ------------------------------------
def test_repo_configs_load_and_resolve_claude():
    ident = ac.AgentIdentity.load(str(_ROOT / "config" / "agent-authors.yaml"))
    assert ident.resolve("claude/agent-calibration-gap", "ianshank") == "claude-code"
    assert ident.resolve("fix/whatever", "ianshank") is None
    cfg = ac.ProxyConfig.load(str(_ROOT / "config" / "agent-confidence.yaml"))
    assert 0.0 < ac.compute_confidence(["agent-core/x.py"], 200, cfg) < 1.0


# --- CLI --------------------------------------------------------------------
def test_cli_agent_path(tmp_path, capsys):
    idp = _write(tmp_path, "id.yaml", _IDENTITY)
    pp = _write(tmp_path, "proxy.yaml", _PROXY)
    rc = ac.main(
        [
            "--files",
            "src/a.py",
            "--lines-changed",
            "80",
            "--head-ref",
            "claude/x",
            "--identity-config",
            idp,
            "--proxy-config",
            pp,
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["agent"] is True
    assert out["agent_version"] == "claude-code"
    assert 0.0 < out["confidence"] < 1.0


def test_cli_human_path(tmp_path, capsys):
    idp = _write(tmp_path, "id.yaml", _IDENTITY)
    pp = _write(tmp_path, "proxy.yaml", _PROXY)
    rc = ac.main(["--files", "src/a.py", "--head-ref", "feat/x", "--identity-config", idp, "--proxy-config", pp])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {"agent": False, "agent_version": None, "confidence": None}


def test_cli_files_from_and_output(tmp_path):
    idp = _write(tmp_path, "id.yaml", _IDENTITY)
    pp = _write(tmp_path, "proxy.yaml", _PROXY)
    files_z = tmp_path / "files.z"
    files_z.write_bytes(b"agent-core/a.py\x00tests/test_a.py\x00")
    out = tmp_path / "out.json"
    rc = ac.main(
        [
            "--files-from",
            str(files_z),
            "--lines-changed",
            "60",
            "--head-ref",
            "claude/y",
            "--identity-config",
            idp,
            "--proxy-config",
            pp,
            "--output",
            str(out),
        ]
    )
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["agent"] is True and payload["agent_version"] == "claude-code"


def test_cli_config_error_exits_2(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("agents: []\nschema_version: '1.0.0'\n", encoding="utf-8")
    rc = ac.main(["--head-ref", "claude/x", "--identity-config", str(bad)])
    assert rc == 2
