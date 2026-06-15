#!/usr/bin/env python3
"""Validation script for Feature F-003: Skill Template and Validator Infrastructure."""
import os
import sys
import importlib.util

def validate_f003() -> bool:
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    # 1. Check docs/SKILL_TEMPLATE.md exists
    skill_temp = os.path.join(project_root, "docs", "SKILL_TEMPLATE.md")
    if not os.path.isfile(skill_temp):
        print(f"FAIL: Missing SKILL_TEMPLATE.md at {skill_temp}")
        return False
        
    # 2. Check docs/SKILL_VALIDATION_TEMPLATE.md exists
    val_temp = os.path.join(project_root, "docs", "SKILL_VALIDATION_TEMPLATE.md")
    if not os.path.isfile(val_temp):
        print(f"FAIL: Missing SKILL_VALIDATION_TEMPLATE.md at {val_temp}")
        return False
        
    # 3. Check scripts/validate_skill.py exists
    val_script = os.path.join(project_root, "scripts", "validate_skill.py")
    if not os.path.isfile(val_script):
        print(f"FAIL: Missing validate_skill.py at {val_script}")
        return False
        
    # 4. Check scripts/validate_skill.py is importable (no syntax errors)
    try:
        spec = importlib.util.spec_from_file_location("validate_skill", val_script)
        if spec is None or spec.loader is None:
            print("FAIL: Could not create import spec for validate_skill.py")
            return False
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as e:
        print(f"FAIL: validate_skill.py has syntax or import errors: {e}")
        return False
        
    # 5. Check skills/ directory exists
    skills_dir = os.path.join(project_root, "skills")
    os.makedirs(skills_dir, exist_ok=True)
    if not os.path.isdir(skills_dir):
        print(f"FAIL: skills/ is not a directory at {skills_dir}")
        return False
        
    print("OK: F-003 validation passed.")
    return True

if __name__ == "__main__":
    if not validate_f003():
        sys.exit(1)
    sys.exit(0)
