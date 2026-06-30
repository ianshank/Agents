from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from eval_harness.config.models import ComponentSpec, EvalConfig, JudgeBudgetConfig, RunSettings
from eval_harness.engine import EvalEngine
from eval_harness.judges import MockJudge

# agent_core is an optional dependency for this feature; skip the whole module if absent.
pytest.importorskip("agent_core")

from agent_core import BudgetExceededError

from eval_harness.agent_core_adapter import BudgetedJudge, build_budgeted_judge


def _budget(**kw):
    base = {"enabled": True, "cap": 2.0, "cost_per_call": 1.0}
    base.update(kw)
    return JudgeBudgetConfig(**base)


def test_under_budget_records_spend():
    j = build_budgeted_judge(MockJudge(default_score=0.6), _budget(cap=2.0))
    assert j.evaluate("p").score == 0.6
    assert j.evaluate("p").score == 0.6


def test_exhausted_budget_raises():
    j = build_budgeted_judge(MockJudge(), _budget(cap=1.0))
    j.evaluate("p")
    with pytest.raises(BudgetExceededError):
        j.evaluate("p")


def test_usable_budget_equals_cap_reserve_zero():
    j = build_budgeted_judge(MockJudge(), _budget(cap=3.0, cost_per_call=1.0))
    admitted = 0
    for _ in range(10):
        try:
            j.evaluate("p")
            admitted += 1
        except BudgetExceededError:
            break
    assert admitted == 3


def test_cost_per_call_scales():
    j = build_budgeted_judge(MockJudge(), _budget(cap=5.0, cost_per_call=2.0))
    j.evaluate("p")  # 2
    j.evaluate("p")  # 4
    with pytest.raises(BudgetExceededError):
        j.evaluate("p")  # would be 6 > 5


def test_on_exceeded_skip_returns_sentinel():
    j = build_budgeted_judge(MockJudge(default_score=0.9), _budget(cap=1.0, on_exceeded="skip"))
    assert j.evaluate("p").score == 0.9
    sentinel = j.evaluate("p")
    assert sentinel.score == 0.0
    assert "budget" in sentinel.reasoning


def test_skip_score_is_configurable():
    j = build_budgeted_judge(MockJudge(default_score=0.9), _budget(cap=1.0, on_exceeded="skip", skip_score=0.5))
    j.evaluate("p")  # consumes the only unit
    sentinel = j.evaluate("p")
    assert sentinel.score == 0.5


def test_skip_score_out_of_range_rejected_at_config():
    with pytest.raises(ValueError):
        JudgeBudgetConfig(enabled=True, cap=1.0, skip_score=1.5)


def test_parallel_safety_never_exceeds_cap():
    # C2 regression guard: under concurrency the cap must hold and no call that
    # was admitted should be retroactively rejected.
    cap = 50
    j = build_budgeted_judge(MockJudge(default_score=1.0), _budget(cap=float(cap), cost_per_call=1.0))
    admitted = 0
    rejected = 0

    def _call(_):
        nonlocal admitted, rejected
        try:
            j.evaluate("p")
            return True
        except BudgetExceededError:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(_call, range(200)))
    admitted = sum(1 for r in results if r)
    rejected = sum(1 for r in results if not r)
    assert admitted == cap  # exactly cap calls admitted, never more
    assert rejected == 200 - cap
    # ledger spend never exceeded the cap
    assert j._ledger.spent <= cap + 1e-9


def test_invalid_on_exceeded_rejected_at_config():
    with pytest.raises(ValueError, match="on_exceeded"):
        JudgeBudgetConfig(enabled=True, cap=1.0, on_exceeded="bogus")


def test_cap_must_be_positive():
    with pytest.raises(ValueError):
        JudgeBudgetConfig(enabled=True, cap=0)


def test_cost_per_call_must_be_positive():
    with pytest.raises(ValueError):
        JudgeBudgetConfig(enabled=True, cap=1.0, cost_per_call=0)


def test_cap_required_when_enabled_at_config_level():
    # Pydantic model validator fails fast at parse time.
    with pytest.raises(ValueError, match="cap must be set"):
        JudgeBudgetConfig(enabled=True)


def test_disabled_without_cap_is_valid():
    # Disabled budgets don't require a cap.
    cfg = JudgeBudgetConfig(enabled=False)
    assert cfg.cap is None


def test_build_guard_when_cap_missing():
    # Defense-in-depth: bypass validation via model_construct and confirm the
    # builder still refuses a capless enabled budget.
    bad = JudgeBudgetConfig.model_construct(enabled=True, cap=None, cost_per_call=1.0, on_exceeded="raise")
    with pytest.raises(ValueError, match="cap must be set"):
        build_budgeted_judge(MockJudge(), bad)


def test_invalid_on_exceeded_rejected_in_wrapper():
    from agent_core import BudgetConfig, BudgetLedger, FrameworkConfig

    ledger = BudgetLedger(FrameworkConfig(budget=BudgetConfig(cap_units=1.0, reserve_fraction=0.0)))
    with pytest.raises(ValueError, match="on_exceeded"):
        BudgetedJudge(MockJudge(), ledger, cost_per_call=1.0, on_exceeded="nope")


def _engine_cfg(**update):
    cfg = EvalConfig(
        schema_version="1.0",
        run=RunSettings(name="v"),
        dataset=ComponentSpec(type="inline", params={"items": [{"id": "a", "inputs": {}, "expected": "x"}]}),
        target=ComponentSpec(type="echo", params={}),
        scorers=[],
        judge=ComponentSpec(type="mock", params={}),
    )
    return cfg.model_copy(update=update) if update else cfg


def test_engine_unwrapped_when_disabled():
    engine = EvalEngine.from_config(_engine_cfg())
    assert not isinstance(engine.judge, BudgetedJudge)


def test_engine_wrapped_when_enabled():
    engine = EvalEngine.from_config(_engine_cfg(judge_budget=_budget(cap=5.0)))
    assert isinstance(engine.judge, BudgetedJudge)


def test_attach_client_delegates_to_inner():
    class _Recorder(MockJudge):
        attached = None

        def attach_client(self, client):
            self.attached = client

    inner = _Recorder()
    j = build_budgeted_judge(inner, _budget(cap=1.0))
    j.attach_client("client-x")
    assert inner.attached == "client-x"


def test_attach_client_noop_when_inner_lacks_it():
    # MockJudge has no attach_client; wrapper must silently no-op (no crash).
    j = build_budgeted_judge(MockJudge(), _budget(cap=1.0))
    j.attach_client("ignored")  # should not raise
    assert j.evaluate("p").score == 1.0
