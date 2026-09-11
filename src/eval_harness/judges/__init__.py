"""Built-in judges. ``mock`` is deterministic and offline; ``bedrock`` is real.

Implementations live in sibling modules (the ``panel.py`` pattern) so this
package stays under the 500-line file budget. Public names are re-exported
here so ``from eval_harness.judges import OpenAIJudge`` keeps working. No
``__all__`` — F-039 only freezes modules that declare one.
"""

from __future__ import annotations

from ..plugins import JUDGES as JUDGES
from . import panel as panel  # registration side effect; mirrors scorers/__init__.py + trajectory.py
from .anthropic import DEFAULT_ANTHROPIC_JUDGE_MODEL as DEFAULT_ANTHROPIC_JUDGE_MODEL
from .anthropic import AnthropicJudge as AnthropicJudge
from .bedrock import BedrockJudge as BedrockJudge
from .mock import MockJudge as MockJudge
from .openai import DEFAULT_RETRY_MAX_ATTEMPTS as DEFAULT_RETRY_MAX_ATTEMPTS
from .openai import DEFAULT_RETRY_WAIT_MAX_SECONDS as DEFAULT_RETRY_WAIT_MAX_SECONDS
from .openai import DEFAULT_RETRY_WAIT_MIN_SECONDS as DEFAULT_RETRY_WAIT_MIN_SECONDS
from .openai import OpenAIJudge as OpenAIJudge
from .phoenix_evals import PhoenixEvalJudge as PhoenixEvalJudge
