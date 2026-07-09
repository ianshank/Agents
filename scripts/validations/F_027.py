#!/usr/bin/env python3
"""Validation script for F-027 — real model-backed target.

Deterministic and offline (no network, no real SDK client): injects a stub
client into ``ModelTarget`` and asserts the registry wiring, the completion
path, latency/metadata, the prompt-template rendering, the error path, and that
the config schema is untouched.

    1. ``model`` (alias ``llm``) is registered in the TARGETS registry.
    2. A stubbed openai-provider target returns the model text with latency.
    3. ``prompt_template`` formats from ``item.inputs``.
    4. A raising client surfaces as ``TargetOutput.error`` (never propagates).
    5. An EvalConfig with ``target.type == "model"`` validates; SCHEMA_VERSION
       is unchanged.

Exit codes: 0 all checks passed; 1 one or more failed.
"""

from __future__ import annotations

import logging
import os
import sys
from unittest.mock import MagicMock

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from _common import check as _check
from _common import configure_logging, report

from eval_harness.core.types import EvalItem
from eval_harness.plugins import TARGETS, bootstrap
from eval_harness.targets.model import ModelTarget
from eval_harness.version import SCHEMA_VERSION


def _openai_stub(text: str) -> MagicMock:
    chunk = MagicMock()
    chunk.choices[0].delta.content = text
    client = MagicMock()
    client.chat.completions.create.return_value = [chunk]
    return client


def validate_f027() -> int:
    configure_logging()
    logger = logging.getLogger("validations.F-027")
    errors: list[str] = []

    bootstrap()
    _check("model" in TARGETS.names(), "model target registered", errors)
    _check("llm" in TARGETS, "llm alias resolves", errors)

    target = TARGETS.create("model", {"provider": "openai", "model": "m", "client": _openai_stub("hi there")})
    _check(isinstance(target, ModelTarget), "registry builds a ModelTarget", errors)

    out = target.run(EvalItem(id="1", inputs={"prompt": "hello"}))
    _check(out.output == "hi there", "returns the model completion text", errors)
    _check(out.error is None and out.latency_ms is not None, "records latency, no error", errors)
    _check(out.metadata == {"provider": "openai", "model": "m"}, "carries provider/model metadata", errors)

    templated = ModelTarget(provider="openai", model="m", prompt_template="Q: {q}", client=_openai_stub("ok"))
    templated.run(EvalItem(id="2", inputs={"q": "why"}))
    sent = templated.client.chat.completions.create.call_args.kwargs["messages"][-1]["content"]
    _check(sent == "Q: why", "prompt_template formats from item.inputs", errors)

    raising = MagicMock()
    raising.chat.completions.create.side_effect = RuntimeError("boom")
    err_out = ModelTarget(provider="openai", model="m", client=raising).run(EvalItem(id="3", inputs={"prompt": "x"}))
    _check(err_out.output is None and err_out.error == "boom", "model failure surfaced as error", errors)

    try:
        ModelTarget(provider="nope", model="m", client=MagicMock())
        bad_provider_rejected = False
    except ValueError:
        bad_provider_rejected = True
    _check(bad_provider_rejected, "invalid provider rejected", errors)

    from eval_harness.config.models import EvalConfig

    cfg = EvalConfig.model_validate(
        {
            "schema_version": SCHEMA_VERSION,
            "run": {"name": "m"},
            "dataset": {"type": "inline", "params": {"items": [{"id": "1", "inputs": {"prompt": "x"}}]}},
            "target": {"type": "model", "params": {"provider": "openai", "model": "m"}},
            "scorers": [{"type": "exact_match", "params": {}}],
        }
    )
    _check(cfg.target.type == "model", "EvalConfig accepts the model target", errors)
    _check(SCHEMA_VERSION == "1.0", "SCHEMA_VERSION unchanged", errors)

    return report(logger, "F-027", errors)


if __name__ == "__main__":
    sys.exit(validate_f027())
