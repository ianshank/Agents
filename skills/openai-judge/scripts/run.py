#!/usr/bin/env python3
"""Execution script for the openai-judge skill.

Acts as a standalone CLI wrapping OpenAIJudge, supporting both mock mode
(for local validation/testing) and live API mode.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from pathlib import Path


def _load_openai_judge():
    """Load OpenAIJudge without requiring eval_harness on the static analysis path."""
    for parent in Path(__file__).resolve().parents:
        src_dir = parent / "src"
        if (src_dir / "eval_harness").is_dir():
            sys.path.insert(0, str(src_dir))
            break

    return importlib.import_module("eval_harness.judges").OpenAIJudge

def main() -> int:
    parser = argparse.ArgumentParser(description="Run OpenAI-compatible LLM judge.")
    parser.add_argument("--model", default="nvidia/nemotron-3-ultra-550b-a55b")
    parser.add_argument("--base-url", default="https://integrate.api.nvidia.com/v1")
    parser.add_argument("--api-key")
    parser.add_argument("--prompt", required=True, help="Path to input prompt file.")
    parser.add_argument("--rubric", required=True, help="Path to grading rubric file.")
    parser.add_argument("--out", required=True, help="Path to write the results json.")
    parser.add_argument("--mock", action="store_true", help="Run in mock offline mode.")
    args = parser.parse_args()

    # Read inputs
    try:
        with open(args.prompt, encoding="utf-8") as f:
            prompt_content = f.read()
        with open(args.rubric, encoding="utf-8") as f:
            rubric_content = f.read()
    except Exception as e:
        print(f"Error reading input files: {e}", file=sys.stderr)
        return 1

    # Ensure output dir exists
    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True)

    if args.mock:
        # Mock mode: deterministic output for offline validation
        verdict = {
            "status": "ok",
            "score": 1.0,
            "reasoning": "Mock judgment passed for offline evaluation."
        }
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(verdict, f, indent=2)
        print("OK: Mock run succeeded.")
        return 0

    # Live API mode: imports from eval_harness
    try:
        openai_judge_cls = _load_openai_judge()
    except (ImportError, AttributeError):
        print("Error: langfuse-eval-harness must be installed to run this skill in live mode.", file=sys.stderr)
        return 1

    try:
        # Combine prompt and rubric
        full_prompt = f"Prompt:\n{prompt_content}\n\nRubric:\n{rubric_content}"
        judge = openai_judge_cls(
            model=args.model,
            base_url=args.base_url,
            api_key=args.api_key or os.environ.get("NVIDIA_API_KEY"),
        )
        res = judge.evaluate(full_prompt)
        verdict = {
            "status": "ok",
            "score": res.score,
            "reasoning": res.reasoning,
            "raw": res.raw
        }
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(verdict, f, indent=2)
        print("OK: Live run succeeded.")
        return 0
    except Exception as e:
        print(f"Error during LLM evaluation: {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
