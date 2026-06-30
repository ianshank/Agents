"""Judge prompt resolution (F-026).

Resolves a :class:`~eval_harness.config.models.PromptSourceConfig` into the
system-prompt string a judge should use, sourcing it from the Langfuse prompt
registry when configured and falling back to inline config text otherwise.

The fallback is deliberate and config-driven (mirrors the no-op tracing fallback
in F-005): an offline run, a missing ``langfuse`` install, or a missing/renamed
prompt never breaks evaluation — it degrades to the inline ``text``.
"""

from __future__ import annotations

import logging

from .config.models import PromptSourceConfig
from .langfuse_client import LangfuseClient

logger = logging.getLogger(__name__)


def resolve_prompt(spec: PromptSourceConfig, client: LangfuseClient | None) -> str | None:
    """Return the system prompt for ``spec``, or ``None`` if nothing resolves.

    * ``source='yaml'`` -> the inline ``text``.
    * ``source='langfuse'`` -> ``client.get_prompt(...)`` when a client is
      available and returns text; otherwise the inline ``text`` fallback.
    """
    if spec.source == "yaml":
        return spec.text

    # source == 'langfuse'
    if client is not None and spec.name is not None:
        fetched = client.get_prompt(spec.name, version=spec.version, label=spec.label)
        if fetched is not None:
            return fetched
        logger.info("Langfuse prompt %r unavailable; falling back to inline judge_prompt.text", spec.name)
    else:
        logger.info("No Langfuse client for prompt %r; falling back to inline judge_prompt.text", spec.name)
    return spec.text
