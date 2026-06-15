"""Run the harness programmatically, fully offline (no network, no SDK)."""
from __future__ import annotations

from pathlib import Path

from eval_harness.config import load_config
from eval_harness.engine import EvalEngine
from eval_harness.gating import evaluate_gate
from eval_harness.langfuse_client import NullLangfuseClient

CONFIG = Path(__file__).resolve().parent.parent / "config" / "eval.example.yaml"


def main() -> None:
    config = load_config(CONFIG)
    client = NullLangfuseClient()  # swap for SDKLangfuseClient(...) in production
    engine = EvalEngine.from_config(config, langfuse_client=client)
    run = engine.run()
    print(f"\nlogged {len(client.scores)} score(s) to (null) Langfuse")
    gate = evaluate_gate(config.gate, run)
    print("gate:", "PASS" if gate.passed else f"FAIL {gate.failures}")


if __name__ == "__main__":
    main()
