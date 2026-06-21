#!/usr/bin/env python3
"""Validation script for Feature F-004: First Real Skill (openai-judge)."""
import os
import subprocess
import sys


def validate_f004() -> bool:
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    val_script = os.path.join(project_root, "scripts", "validate_skill.py")
    skill_dir = os.path.join(project_root, "skills", "openai-judge")

    if not os.path.isfile(val_script):
        print(f"FAIL: validate_skill.py not found at {val_script}")
        return False
    if not os.path.isdir(skill_dir):
        print(f"FAIL: openai-judge skill dir not found at {skill_dir}")
        return False

    cmd = [
        sys.executable,
        val_script,
        "--skill",
        skill_dir,
        "--tier",
        "structural,behavioral"
    ]

    print(f"Running command: {' '.join(cmd)}")
    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120
        )
        print("STDOUT:")
        print(res.stdout)
        print("STDERR:")
        print(res.stderr)

        if res.returncode == 0:
            print("OK: F-004 validation passed.")
            return True
        else:
            print(f"FAIL: validate_skill.py exited with non-zero code {res.returncode}")
            return False
    except Exception as e:
        print(f"FAIL: Validation script crashed: {e}")
        return False

if __name__ == "__main__":
    if not validate_f004():
        sys.exit(1)
    sys.exit(0)
