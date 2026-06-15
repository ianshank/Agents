import json
import os
import shutil
import pytest
from unittest.mock import patch, MagicMock

from scripts.validate_skill import parse_frontmatter, check_structural, check_behavioral, grade

def test_parse_frontmatter(tmp_path):
    skill_md = tmp_path / "SKILL.md"
    
    # 1. Valid frontmatter
    skill_md.write_text("---\nname: my-skill\ndescription: Use whenever you want to test.\n---\nBody content here.", encoding="utf-8")
    fm, nlines = parse_frontmatter(str(skill_md))
    assert fm == {"name": "my-skill", "description": "Use whenever you want to test."}
    assert nlines == 5

    # 2. No frontmatter
    skill_md.write_text("No frontmatter here.", encoding="utf-8")
    fm, nlines = parse_frontmatter(str(skill_md))
    assert fm is None
    assert nlines == 1

def test_check_structural_valid(tmp_path):
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text("---\nname: my-skill\ndescription: Use when the user asks to validate a skill.\n---\nBody", encoding="utf-8")
    
    # Matching directory name
    skill_dir = tmp_path / "my-skill"
    skill_dir.mkdir()
    shutil.copy(str(skill_md), str(skill_dir / "SKILL.md"))
    
    errs, warns = check_structural(str(skill_dir), "evals/evals.json")
    assert not errs
    assert not warns

def test_check_structural_missing_skill_md(tmp_path):
    errs, warns = check_structural(str(tmp_path), "evals/evals.json")
    assert "missing" in errs[0]

def test_check_structural_invalid_frontmatter(tmp_path):
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text("No yaml", encoding="utf-8")
    errs, warns = check_structural(str(tmp_path), "evals/evals.json")
    assert "no YAML frontmatter" in errs[0]

def test_check_structural_placeholders(tmp_path):
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text("---\nname: {{skill-name}}\ndescription: {{placeholder}}\n---\nBody", encoding="utf-8")
    errs, warns = check_structural(str(tmp_path), "evals/evals.json")
    assert any("name' missing or placeholder" in e for e in errs)
    assert any("description' missing or placeholder" in e for e in errs)

def test_check_structural_warnings(tmp_path):
    # Short description, lacks trigger word
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text("---\nname: MySkill\ndescription: Short.\n---\n" + "\n" * 600, encoding="utf-8")
    errs, warns = check_structural(str(tmp_path), "evals/evals.json")
    # directory base != name -> warn
    # name MySkill not lowercase-hyphen -> warn
    # description short -> warn
    # description lacks trigger -> warn
    # lines > 500 -> warn
    assert any("lowercase-hyphen" in w for w in warns)
    assert any("dir" in w for w in warns)
    assert any("very short" in w for w in warns)
    assert any("trigger phrase" in w for w in warns)
    assert any("lines (>500)" in w for w in warns)

def test_grade_exit_zero():
    # exit_zero passes when code 0
    res = grade({"type": "exit_zero", "text": "pass"}, 0, "", True, ".", 10)
    assert res["passed"]
    
    # fails when non-zero
    res = grade({"type": "exit_zero", "text": "fail"}, 1, "", True, ".", 10)
    assert not res["passed"]

    # fails when no run
    res = grade({"type": "exit_zero", "text": "fail"}, 0, "", False, ".", 10)
    assert not res["passed"]

def test_grade_output_contains():
    res = grade({"type": "output_contains", "contains": "hello"}, 0, "hello world", True, ".", 10)
    assert res["passed"]
    
    res = grade({"type": "output_contains", "contains": "missing"}, 0, "hello world", True, ".", 10)
    assert not res["passed"]

def test_grade_file_contains(tmp_path):
    file_path = tmp_path / "test.txt"
    file_path.write_text("my custom content", encoding="utf-8")
    
    res = grade({"type": "file_contains", "path": "test.txt", "contains": "custom"}, 0, "", True, str(tmp_path), 10)
    assert res["passed"]
    
    res = grade({"type": "file_contains", "path": "test.txt", "contains": "absent"}, 0, "", True, str(tmp_path), 10)
    assert not res["passed"]
    
    # Missing file
    res = grade({"type": "file_contains", "path": "missing.txt", "contains": "x"}, 0, "", True, str(tmp_path), 10)
    assert not res["passed"]

def test_grade_command_exit_zero():
    res = grade({"type": "command_exit_zero", "cmd": "python -c \"exit(0)\""}, 0, "", True, ".", 10)
    assert res["passed"]
    
    res = grade({"type": "command_exit_zero", "cmd": "python -c \"exit(1)\""}, 0, "", True, ".", 10)
    assert not res["passed"]

def test_check_behavioral_errors(tmp_path):
    evals_json = tmp_path / "evals.json"
    
    # 1. No assertions
    evals_json.write_text(json.dumps({
        "skill": "my-skill",
        "evals": [{"id": "test", "run": "python -c \"\""}]
    }), encoding="utf-8")
    errs = check_behavioral(str(tmp_path), "evals.json", 10)
    assert "no assertions" in errs[0]

    # 2. Executes nothing
    evals_json.write_text(json.dumps({
        "skill": "my-skill",
        "evals": [{"id": "test", "assertions": [{"type": "file_exists", "path": "test.txt"}]}]
    }), encoding="utf-8")
    errs = check_behavioral(str(tmp_path), "evals.json", 10)
    assert "executes nothing" in errs[0]

    # 3. Only existence checks (no behavioral assertions)
    evals_json.write_text(json.dumps({
        "skill": "my-skill",
        "evals": [{
            "id": "test",
            "run": "python -c \"\"",
            "assertions": [{"type": "file_exists", "path": "test.txt"}]
        }]
    }), encoding="utf-8")
    errs = check_behavioral(str(tmp_path), "evals.json", 10)
    assert "add a behavioral assertion" in errs[0]

def test_check_behavioral_valid(tmp_path):
    evals_json = tmp_path / "evals.json"
    evals_json.write_text(json.dumps({
        "skill": "my-skill",
        "evals": [{
            "id": "test",
            "run": "python -c \"print('success')\"",
            "assertions": [
                {"type": "exit_zero"},
                {"type": "output_contains", "contains": "success"}
            ]
        }]
    }), encoding="utf-8")
    errs = check_behavioral(str(tmp_path), "evals.json", 10)
    assert not errs
    
    # Check grading.json is written
    grading = tmp_path / ".skill-validation" / "grading.json"
    assert grading.is_file()
    with open(grading, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["results"][0]["eval_id"] == "test"
