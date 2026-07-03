from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "hooks"
TOOLS = ROOT / "tools"
for _p in (str(TOOLS), str(HOOKS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def make_plugin_tree(root: Path) -> Path:
    """Build a minimal, fully valid plugin tree for validator/scanner tests."""
    manifest_dir = root / ".claude-plugin"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "plugin.json").write_text(
        json.dumps({"name": "demo", "version": "1.0.0", "description": "demo plugin"}),
        encoding="utf-8",
    )
    (manifest_dir / "marketplace.json").write_text(
        json.dumps(
            {
                "name": "demo-market",
                "owner": {"name": "Demo"},
                "plugins": [{"name": "demo", "source": "./"}],
            }
        ),
        encoding="utf-8",
    )

    skill_dir = root / "skills" / "hello"
    (skill_dir / "evals").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: hello\ndescription: Says hello when asked for a greeting.\n---\n\nSay hello.\n",
        encoding="utf-8",
    )
    (skill_dir / "evals" / "evals.json").write_text(
        json.dumps(
            {
                "skill": "hello",
                "version": 1,
                "cases": [
                    {
                        "id": f"case-{i}",
                        "prompt": f"prompt {i}",
                        "expected_behavior": "greets",
                        "assertions": ["says hello"],
                    }
                    for i in range(3)
                ],
            }
        ),
        encoding="utf-8",
    )

    agents_dir = root / "agents"
    agents_dir.mkdir()
    (agents_dir / "scout.md").write_text(
        "---\nname: scout\ndescription: Read-only scout.\ntools: Read, Grep\nmodel: haiku\n---\n\nScout.\n",
        encoding="utf-8",
    )

    hooks_dir = root / "hooks"
    hooks_dir.mkdir()
    (hooks_dir / "hooks.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Read",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": 'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/guard.py"',
                                }
                            ],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    return root


@pytest.fixture
def plugin_tree(tmp_path: Path) -> Path:
    return make_plugin_tree(tmp_path / "plugin")
