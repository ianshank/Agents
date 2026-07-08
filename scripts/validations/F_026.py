#!/usr/bin/env python3
"""Validation script for F-026 — Langfuse judge-prompt management.

Deterministic and offline (no network, no Langfuse install required):

    1. ``PromptSourceConfig`` validates: yaml needs ``text``; langfuse needs ``name``.
    2. ``resolve_prompt`` returns the inline text for ``source='yaml'``.
    3. ``resolve_prompt`` falls back to the inline text when a Langfuse prompt is
       unavailable (NullLangfuseClient.get_prompt -> None).
    4. ``resolve_prompt`` returns the registry text when the client supplies it.
    5. ``NullLangfuseClient.get_prompt`` defaults to ``None`` (offline-safe).
    6. ``EvalConfig`` accepts the optional ``judge_prompt`` block with the schema
       version unchanged (additive, backwards-compatible).

Exit codes: 0 all checks passed; 1 one or more failed.
"""

from __future__ import annotations

import logging
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from _common import check as _check
from _common import configure_logging, report

from eval_harness.config.models import EvalConfig, PromptSourceConfig
from eval_harness.langfuse_client import NullLangfuseClient
from eval_harness.prompts import resolve_prompt
from eval_harness.version import SCHEMA_VERSION


class _PromptClient(NullLangfuseClient):
    """Offline client whose registry returns a fixed prompt."""

    def get_prompt(self, name, version=None, label=None):  # type: ignore[override]
        return f"REGISTRY::{name}"


def _validation_raises(**kwargs) -> bool:
    try:
        PromptSourceConfig(**kwargs)
        return False
    except Exception:
        return True


def validate_f026() -> int:
    configure_logging()
    logger = logging.getLogger("validations.F-026")
    errors: list[str] = []

    # 1. validation rules
    _check(_validation_raises(source="yaml"), "yaml source requires text", errors)
    _check(_validation_raises(source="langfuse"), "langfuse source requires name", errors)
    _check(_validation_raises(source="bogus", text="x"), "source must be yaml|langfuse", errors)

    yaml_spec = PromptSourceConfig(source="yaml", text="INLINE")
    lf_spec = PromptSourceConfig(source="langfuse", name="judge-rubric", text="FALLBACK")

    # 2. yaml source -> inline text
    _check(resolve_prompt(yaml_spec, None) == "INLINE", "yaml resolves to inline text", errors)

    # 3. langfuse unavailable -> fallback text (NullLangfuseClient returns None)
    _check(
        resolve_prompt(lf_spec, NullLangfuseClient()) == "FALLBACK",
        "langfuse falls back to inline text when prompt is unavailable",
        errors,
    )
    _check(
        resolve_prompt(lf_spec, None) == "FALLBACK",
        "langfuse falls back to inline text when no client is wired",
        errors,
    )

    # 4. langfuse available -> registry text
    _check(
        resolve_prompt(lf_spec, _PromptClient()) == "REGISTRY::judge-rubric",
        "langfuse returns registry prompt when available",
        errors,
    )

    # 5. offline-safe default
    _check(NullLangfuseClient().get_prompt("x") is None, "NullLangfuseClient.get_prompt is None", errors)

    # 6. EvalConfig accepts judge_prompt, schema version unchanged
    # Build from a raw mapping via model_validate (Pydantic coerces the nested dicts into
    # the typed sub-models) — keeps mypy honest about the dict->model boundary without
    # loosening the model's field types.
    cfg = EvalConfig.model_validate(
        {
            "schema_version": SCHEMA_VERSION,
            "dataset": {"type": "inline", "params": {}},
            "target": {"type": "echo", "params": {}},
            "judge": {"type": "mock", "params": {}},
            "judge_prompt": {"source": "langfuse", "name": "judge-rubric", "text": "FB"},
        }
    )
    _check(cfg.judge_prompt is not None, "EvalConfig carries judge_prompt", errors)
    _check(cfg.schema_version == SCHEMA_VERSION, "schema_version unchanged", errors)

    return report(logger, "F-026", errors)


if __name__ == "__main__":
    sys.exit(validate_f026())
