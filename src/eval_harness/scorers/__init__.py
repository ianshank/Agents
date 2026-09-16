"""Built-in scorers. Each registers under a stable name (plus aliases).

Implementations live in sibling modules (the ``panel.py`` pattern) so this
package stays well inside the 500-line ceiling ``scripts/check_size_budget.py`` enforces.
Public names are re-exported here so ``from eval_harness.scorers import ExactMatchScorer``
keeps working. No ``__all__`` — F-039 only freezes modules that declare one.
"""

from __future__ import annotations

from ..plugins import SCORERS as SCORERS
from . import rca as rca
from . import requirements as requirements
from . import state as state
from . import test_generation as test_generation
from . import trajectory as trajectory
from .basic import AutoevalsScorer as AutoevalsScorer
from .basic import CompositeScorer as CompositeScorer
from .basic import ContainsScorer as ContainsScorer
from .basic import ExactMatchScorer as ExactMatchScorer
from .basic import JsonKeysScorer as JsonKeysScorer
from .basic import LLMJudgeScorer as LLMJudgeScorer
from .basic import RegexMatchScorer as RegexMatchScorer
