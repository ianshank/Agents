from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

main = import_module("eval_harness.cli").main
load_config = import_module("eval_harness.config").load_config
migrate_to_current = import_module("eval_harness.config.migrations").migrate_to_current
EvalEngine = import_module("eval_harness.engine").EvalEngine
NullLangfuseClient = import_module("eval_harness.langfuse_client").NullLangfuseClient
SCHEMA_VERSION = import_module("eval_harness.version").SCHEMA_VERSION

CONFIG_DIR = PROJECT_ROOT / "config"


def test_migration_0_9_renames_fields():
    raw = {
        "schema_version": "0.9",
        "dataset": {"type": "inline", "params": {"items": []}},
        "target": {"type": "echo"},
        "evaluators": [{"type": "exact"}],
        "sink": {"type": "console"},
    }
    migrated = migrate_to_current(raw)
    assert migrated["schema_version"] == SCHEMA_VERSION
    assert "scorers" in migrated and "evaluators" not in migrated
    assert migrated["sinks"] == [{"type": "console"}]


def test_legacy_config_file_loads_and_runs():
    config = load_config(CONFIG_DIR / "legacy.v0_9.yaml")
    assert config.schema_version == SCHEMA_VERSION
    # 'exact' alias resolves to exact_match
    engine = EvalEngine.from_config(config, langfuse_client=NullLangfuseClient())
    run = engine.run()
    assert run.aggregate["exact"].mean == 1.0


def test_example_config_offline_run(tmp_path, monkeypatch):
    monkeypatch.setenv("OUT_DIR", str(tmp_path))
    config = load_config(CONFIG_DIR / "eval.example.yaml")
    engine = EvalEngine.from_config(config, langfuse_client=NullLangfuseClient())
    run = engine.run()
    assert (tmp_path / "results.json").exists()
    assert "helpfulness" in run.aggregate


def test_cli_list_plugins(capsys):
    assert main(["list-plugins"]) == 0
    out = capsys.readouterr().out
    assert "scorers:" in out and "llm_judge" in out


def test_cli_run_offline_gate_pass(tmp_path, monkeypatch):
    monkeypatch.setenv("OUT_DIR", str(tmp_path))
    code = main(["run", "--config", str(CONFIG_DIR / "eval.example.yaml"), "--offline"])
    assert code == 0


def test_cli_run_gate_fail(tmp_path, monkeypatch):
    monkeypatch.setenv("OUT_DIR", str(tmp_path))
    # force an impossible threshold via override
    code = main(
        [
            "run",
            "--config",
            str(CONFIG_DIR / "eval.example.yaml"),
            "--offline",
            "--set",
            "gate.rules=[{score: helpfulness, metric: mean, min: 0.99}]",
        ]
    )
    assert code == 1
