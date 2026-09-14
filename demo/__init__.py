"""Demo package.

Exists so ``demo.support_bot_target:answer`` is importable by the harness's
``callable`` target when the repo root is on ``PYTHONPATH`` (the demo runbook and
``run_demo.sh`` export ``PYTHONPATH=.``). Nothing here is part of the shipped
``eval_harness`` package — it is illustrative demo scaffolding only.

``search_v2`` is re-exported so a one-component override ``demo:search_v2``
resolves the same stub as ``demo.replay_stubs:search_v2``.
"""

from demo.replay_stubs import search_v2 as search_v2
