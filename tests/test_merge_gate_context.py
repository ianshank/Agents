#!/usr/bin/env python3
"""Tests for scripts/merge_gate_context.py — ChangeContext composition (F-035)."""

from __future__ import annotations

import json
from pathlib import Path

import merge_gate_context as mgc
import pytest
import yaml
from check_protected_changes import ConfigError

_VALID = {
    "schema_version": "1.0.0",
    "default_domain": "repo-misc",
    "human_namespace": "human/",
    "rules": [
        {"pattern": "agent-core/**", "domain": "agent-core"},
        {"pattern": "src/**", "domain": "eval-harness"},
        {"pattern": "**/*.md", "domain": "docs"},
    ],
}


def _write_mapping(tmp_path: Path, doc: object) -> str:
    path = tmp_path / "domains.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return str(path)


# --- mapping load ---------------------------------------------------------------
def test_load_valid_mapping(tmp_path):
    mapping = mgc.DomainMapping.load(_write_mapping(tmp_path, _VALID))
    assert mapping.default_domain == "repo-misc"
    assert mapping.human_namespace == "human/"
    assert mapping.rules[0] == mgc.DomainRule(pattern="agent-core/**", domain="agent-core")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(extra_key=1),  # unknown key
        lambda d: d.pop("default_domain"),  # missing key
        lambda d: d.update(schema_version="9.0.0"),  # unsupported schema
        lambda d: d.update(human_namespace="human"),  # namespace must end with /
        lambda d: d.update(human_namespace="bot/"),  # valid form but != canonical HUMAN_NAMESPACE
        lambda d: d.update(rules=[]),  # empty rules
        lambda d: d.update(rules="nope"),  # non-list rules
        lambda d: d.update(rules=[{"pattern": "x/**"}]),  # rule missing domain
        lambda d: d.update(rules=[{"pattern": "x/**", "domain": "human/x"}]),  # reserved ns
        lambda d: d.update(default_domain="human/misc"),  # reserved ns in default
        lambda d: d.update(default_domain=""),  # empty domain
    ],
)
def test_load_rejects_invalid_mapping(tmp_path, mutate):
    doc = {k: (list(v) if isinstance(v, list) else v) for k, v in _VALID.items()}
    mutate(doc)
    with pytest.raises(ConfigError):
        mgc.DomainMapping.load(_write_mapping(tmp_path, doc))


def test_load_accepts_minor_schema_bumps(tmp_path):
    doc = dict(_VALID, schema_version="1.2.0")
    mapping = mgc.DomainMapping.load(_write_mapping(tmp_path, doc))
    assert mapping.schema_version == "1.2.0"  # additive evolution loads fine


def test_load_rejects_unreadable_and_non_mapping(tmp_path):
    with pytest.raises(ConfigError):
        mgc.DomainMapping.load(str(tmp_path / "missing.yaml"))
    with pytest.raises(ConfigError):
        mgc.DomainMapping.load(_write_mapping(tmp_path, ["not", "a", "mapping"]))


def test_committed_mapping_loads_and_never_emits_human(tmp_path):
    import _config

    mapping = mgc.DomainMapping.load(mgc.DEFAULT_MAPPING_PATH)
    assert mapping.schema_version.split(".", 1)[0] == _config.SUPPORTED_SCHEMA_MAJOR
    assert not mapping.default_domain.startswith(mapping.human_namespace)
    assert all(not r.domain.startswith(mapping.human_namespace) for r in mapping.rules)


# --- domain classification --------------------------------------------------------
def test_classify_first_match_wins_in_rule_order(tmp_path):
    mapping = mgc.DomainMapping.load(_write_mapping(tmp_path, _VALID))
    files = ["src/eval_harness/core.py", "agent-core/agent_core/loop.py"]
    # agent-core rule precedes src rule, so it wins even though both match.
    assert mgc.classify_domain(files, mapping) == "agent-core"


def test_classify_nested_markdown_and_default(tmp_path):
    mapping = mgc.DomainMapping.load(_write_mapping(tmp_path, _VALID))
    assert mgc.classify_domain(["docs/plans/x/PLAN.md"], mapping) == "docs"
    assert mgc.classify_domain(["Makefile"], mapping) == "repo-misc"
    assert mgc.classify_domain([], mapping) == "repo-misc"


# --- context composition ------------------------------------------------------------
def test_build_context_shape_and_protected_detection(tmp_path):
    mapping = mgc.DomainMapping.load(_write_mapping(tmp_path, _VALID))
    ctx = mgc.build_context(["config/eval.example.yaml"], mapping, mech_pass=True, human=False, confidence=0.9)
    assert ctx == {
        "mech_pass": True,
        "touches_protected": True,  # config/** is a protected path
        "raw_confidence": 0.9,
        "domain": "repo-misc",
    }
    ctx2 = mgc.build_context(["agent-core/agent_core/loop.py"], mapping, mech_pass=False, human=False, confidence=None)
    assert ctx2["touches_protected"] is False
    assert ctx2["raw_confidence"] == 0.0
    assert ctx2["domain"] == "agent-core"


def test_build_context_human_namespace_forces_zero_confidence(tmp_path):
    mapping = mgc.DomainMapping.load(_write_mapping(tmp_path, _VALID))
    ctx = mgc.build_context(["src/eval_harness/core.py"], mapping, mech_pass=False, human=True, confidence=0.7)
    assert ctx["domain"] == "human/eval-harness"
    assert ctx["raw_confidence"] == 0.0


# --- file-set resolution -------------------------------------------------------------
def test_resolve_files_from_nul_delimited_file(tmp_path):
    listing = tmp_path / "files.z"
    listing.write_text("a.py\0dir/b.md\0\0", encoding="utf-8")
    args = mgc.build_parser().parse_args(["--files-from", str(listing)])
    assert mgc.resolve_files(args) == ["a.py", "dir/b.md"]


def test_main_empty_files_from_defaults_domain(tmp_path, capsys):
    """The seed's real cold case: an empty merge diff still composes a context."""
    mapping_path = _write_mapping(tmp_path, _VALID)
    empty = tmp_path / "empty.z"
    empty.write_text("", encoding="utf-8")
    rc = mgc.main(["--mapping", mapping_path, "--files-from", str(empty), "--human"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["domain"] == "human/repo-misc"  # default domain, namespaced
    assert payload["touches_protected"] is False


def test_resolve_files_missing_files_from_raises(tmp_path):
    args = mgc.build_parser().parse_args(["--files-from", str(tmp_path / "missing.z")])
    with pytest.raises(ConfigError):
        mgc.resolve_files(args)


def test_resolve_files_git_fallback_uses_base_ref_resolution(monkeypatch):
    calls: list[str] = []

    def fake_diff(base_ref: str) -> list[str]:
        calls.append(base_ref)
        return ["x.py"]

    monkeypatch.setattr(mgc, "changed_files_from_git", fake_diff)
    monkeypatch.delenv("BASE_REF", raising=False)
    args = mgc.build_parser().parse_args([])
    assert mgc.resolve_files(args) == ["x.py"]
    monkeypatch.setenv("BASE_REF", "origin/dev")
    mgc.resolve_files(args)
    args2 = mgc.build_parser().parse_args(["--base-ref", "origin/topic"])
    mgc.resolve_files(args2)
    assert calls == ["origin/main", "origin/dev", "origin/topic"]


# --- CLI --------------------------------------------------------------------------
def test_main_writes_output_file(tmp_path):
    mapping_path = _write_mapping(tmp_path, _VALID)
    out = tmp_path / "context.json"
    rc = mgc.main(
        [
            "--mapping",
            mapping_path,
            "--files",
            "agent-core/x.py",
            "--mech-pass",
            "--output",
            str(out),
        ]
    )
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8")) == {
        "mech_pass": True,
        "touches_protected": False,
        "raw_confidence": 0.0,
        "domain": "agent-core",
    }


def test_main_prints_to_stdout_and_human_flag(tmp_path, capsys):
    mapping_path = _write_mapping(tmp_path, _VALID)
    rc = mgc.main(["--mapping", mapping_path, "--files", "src/x.py", "--human"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["domain"] == "human/eval-harness"
    assert payload["mech_pass"] is False  # fail-safe default


def test_main_config_error_exits_2(tmp_path):
    assert mgc.main(["--mapping", str(tmp_path / "missing.yaml"), "--files", "x"]) == 2


def test_main_human_and_confidence_mutually_exclusive(tmp_path):
    mapping_path = _write_mapping(tmp_path, _VALID)
    with pytest.raises(SystemExit) as exc:
        mgc.main(["--mapping", mapping_path, "--files", "x", "--human", "--confidence", "0.5"])
    assert exc.value.code == 2
