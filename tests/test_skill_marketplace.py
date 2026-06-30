from __future__ import annotations

import json
import os

import pytest
import skill_marketplace as mkt
import yaml

_SCHEMA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills", "marketplace.schema.json")

_GOOD_SKILL_MD = "---\nname: {name}\ndescription: a skill used for marketplace tests\ncompatibility: python>=3.10\nversion: {version}\n---\n\n# {name}\n"


def _make_skill(tmp_path, name="demo", version="1.0.0", skill_md=None):
    d = tmp_path / name
    (d / "evals").mkdir(parents=True)
    md = skill_md if skill_md is not None else _GOOD_SKILL_MD.format(name=name, version=version)
    (d / "SKILL.md").write_text(md, encoding="utf-8")
    return d


def _write_registry(tmp_path, skills, registry_version="1.0.0"):
    reg = tmp_path / "marketplace.yaml"
    reg.write_text(yaml.safe_dump({"registry_version": registry_version, "skills": skills}), encoding="utf-8")
    return str(reg)


def test_real_registry_validates_clean():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    registry = os.path.join(root, "skills", "marketplace.yaml")
    assert mkt.validate_registry(registry, _SCHEMA) == []


def test_happy_path(tmp_path, monkeypatch):
    _make_skill(tmp_path, "demo", "1.2.3")
    monkeypatch.setattr(mkt, "_repo_root", lambda: str(tmp_path))
    reg = _write_registry(tmp_path, [{"name": "demo", "version": "1.2.3", "path": "demo"}])
    assert mkt.validate_registry(reg, _SCHEMA) == []


def test_missing_version_in_frontmatter(tmp_path, monkeypatch):
    md = (
        "---\nname: demo\ndescription: a skill without a version key here\ncompatibility: python>=3.10\n---\n\n# demo\n"
    )
    _make_skill(tmp_path, "demo", skill_md=md)
    monkeypatch.setattr(mkt, "_repo_root", lambda: str(tmp_path))
    reg = _write_registry(tmp_path, [{"name": "demo", "version": "1.0.0", "path": "demo"}])
    errs = mkt.validate_registry(reg, _SCHEMA)
    assert any("missing a 'version'" in e for e in errs)


def test_malformed_semver_in_frontmatter(tmp_path, monkeypatch):
    _make_skill(tmp_path, "demo", "1.0")  # not MAJOR.MINOR.PATCH
    monkeypatch.setattr(mkt, "_repo_root", lambda: str(tmp_path))
    reg = _write_registry(tmp_path, [{"name": "demo", "version": "1.0.0", "path": "demo"}])
    errs = mkt.validate_registry(reg, _SCHEMA)
    assert any("not semver" in e for e in errs)


def test_version_mismatch(tmp_path, monkeypatch):
    _make_skill(tmp_path, "demo", "1.0.0")
    monkeypatch.setattr(mkt, "_repo_root", lambda: str(tmp_path))
    reg = _write_registry(tmp_path, [{"name": "demo", "version": "2.0.0", "path": "demo"}])
    errs = mkt.validate_registry(reg, _SCHEMA)
    assert any("!= SKILL.md version" in e for e in errs)


def test_name_mismatch(tmp_path, monkeypatch):
    _make_skill(tmp_path, "demo", "1.0.0")
    monkeypatch.setattr(mkt, "_repo_root", lambda: str(tmp_path))
    # registry calls it "other" but the dir's SKILL.md says "demo"
    reg = _write_registry(tmp_path, [{"name": "other", "version": "1.0.0", "path": "demo"}])
    errs = mkt.validate_registry(reg, _SCHEMA)
    assert any("does not match SKILL.md name" in e for e in errs)


def test_nonexistent_path(tmp_path, monkeypatch):
    monkeypatch.setattr(mkt, "_repo_root", lambda: str(tmp_path))
    reg = _write_registry(tmp_path, [{"name": "ghost", "version": "1.0.0", "path": "nope"}])
    errs = mkt.validate_registry(reg, _SCHEMA)
    assert any("SKILL.md not found" in e for e in errs)


def test_duplicate_name(tmp_path, monkeypatch):
    _make_skill(tmp_path, "demo", "1.0.0")
    monkeypatch.setattr(mkt, "_repo_root", lambda: str(tmp_path))
    reg = _write_registry(
        tmp_path,
        [
            {"name": "demo", "version": "1.0.0", "path": "demo"},
            {"name": "demo", "version": "1.0.0", "path": "demo"},
        ],
    )
    errs = mkt.validate_registry(reg, _SCHEMA)
    assert any("duplicate skill name" in e for e in errs)


def test_schema_rejects_bad_registry_version(tmp_path, monkeypatch):
    _make_skill(tmp_path, "demo", "1.0.0")
    monkeypatch.setattr(mkt, "_repo_root", lambda: str(tmp_path))
    reg = _write_registry(tmp_path, [{"name": "demo", "version": "1.0.0", "path": "demo"}], registry_version="oops")
    errs = mkt.validate_registry(reg, _SCHEMA)
    assert any("does not match schema" in e for e in errs)


def test_registry_not_found():
    with pytest.raises(FileNotFoundError):
        mkt.load_registry("/no/such/registry.yaml")


def test_registry_not_a_mapping(tmp_path):
    reg = tmp_path / "bad.yaml"
    reg.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a mapping"):
        mkt.load_registry(str(reg))


def test_schema_not_found(tmp_path, monkeypatch):
    _make_skill(tmp_path, "demo", "1.0.0")
    monkeypatch.setattr(mkt, "_repo_root", lambda: str(tmp_path))
    reg = _write_registry(tmp_path, [{"name": "demo", "version": "1.0.0", "path": "demo"}])
    errs = mkt.validate_registry(reg, str(tmp_path / "nope.schema.json"))
    assert any("schema not found" in e for e in errs)


def test_cli_validate_ok(tmp_path, monkeypatch, capsys):
    _make_skill(tmp_path, "demo", "1.0.0")
    monkeypatch.setattr(mkt, "_repo_root", lambda: str(tmp_path))
    reg = _write_registry(tmp_path, [{"name": "demo", "version": "1.0.0", "path": "demo"}])
    rc = mkt.main(["--registry", reg, "--schema", _SCHEMA, "validate"])
    assert rc == 0


def test_cli_validate_fails(tmp_path, monkeypatch):
    md = "---\nname: demo\ndescription: a skill without a version here at all\ncompatibility: python>=3.10\n---\n\n# demo\n"
    _make_skill(tmp_path, "demo", skill_md=md)
    monkeypatch.setattr(mkt, "_repo_root", lambda: str(tmp_path))
    reg = _write_registry(tmp_path, [{"name": "demo", "version": "1.0.0", "path": "demo"}])
    rc = mkt.main(["--registry", reg, "--schema", _SCHEMA, "verify"])
    assert rc == 1


def test_cli_validate_missing_registry():
    rc = mkt.main(["--registry", "/no/such.yaml", "validate"])
    assert rc == 2


def test_cli_list(tmp_path, capsys):
    _make_skill(tmp_path, "demo", "1.0.0")
    reg = _write_registry(tmp_path, [{"name": "demo", "version": "1.0.0", "path": "demo"}])
    rc = mkt.main(["--registry", reg, "list"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "demo" in out and "1.0.0" in out


def test_cli_list_missing_registry():
    rc = mkt.main(["--registry", "/no/such.yaml", "list"])
    assert rc == 2


def test_schema_pattern_is_valid_json():
    with open(_SCHEMA, encoding="utf-8") as f:
        schema = json.load(f)
    assert schema["properties"]["skills"]["items"]["required"] == ["name", "version", "path"]
