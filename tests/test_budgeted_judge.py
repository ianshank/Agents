from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

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


def test_under_budget_records_spend() -> None:
    j = build_budgeted_judge(MockJudge(default_score=0.6), _budget(cap=2.0))
    assert j.evaluate("p").score == 0.6
    assert j.evaluate("p").score == 0.6


def test_exhausted_budget_raises() -> None:
    j = build_budgeted_judge(MockJudge(), _budget(cap=1.0))
    j.evaluate("p")
    with pytest.raises(BudgetExceededError):
        j.evaluate("p")


def test_usable_budget_equals_cap_reserve_zero() -> None:
    j = build_budgeted_judge(MockJudge(), _budget(cap=3.0, cost_per_call=1.0))
    admitted = 0
    for _ in range(10):
        try:
            j.evaluate("p")
            admitted += 1
        except BudgetExceededError:
            break
    assert admitted == 3


def test_cost_per_call_scales() -> None:
    j = build_budgeted_judge(MockJudge(), _budget(cap=5.0, cost_per_call=2.0))
    j.evaluate("p")  # 2
    j.evaluate("p")  # 4
    with pytest.raises(BudgetExceededError):
        j.evaluate("p")  # would be 6 > 5


def test_on_exceeded_skip_returns_sentinel() -> None:
    j = build_budgeted_judge(MockJudge(default_score=0.9), _budget(cap=1.0, on_exceeded="skip"))
    assert j.evaluate("p").score == 0.9
    sentinel = j.evaluate("p")
    assert sentinel.score == 0.0
    assert "budget" in sentinel.reasoning


def test_skip_score_is_configurable() -> None:
    j = build_budgeted_judge(MockJudge(default_score=0.9), _budget(cap=1.0, on_exceeded="skip", skip_score=0.5))
    j.evaluate("p")  # consumes the only unit
    sentinel = j.evaluate("p")
    assert sentinel.score == 0.5


def test_skip_score_out_of_range_rejected_at_config() -> None:
    with pytest.raises(ValueError):
        JudgeBudgetConfig(enabled=True, cap=1.0, skip_score=1.5)


def test_parallel_safety_never_exceeds_cap() -> None:
    # C2 regression guard: under concurrency the cap must hold and no call that
    # was admitted should be retroactively rejected.
    cap = 50
    j = build_budgeted_judge(MockJudge(default_score=1.0), _budget(cap=float(cap), cost_per_call=1.0))
    assert isinstance(j, BudgetedJudge)
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


def test_invalid_on_exceeded_rejected_at_config() -> None:
    with pytest.raises(ValueError, match="on_exceeded"):
        JudgeBudgetConfig(enabled=True, cap=1.0, on_exceeded="bogus")


def test_cap_must_be_positive() -> None:
    with pytest.raises(ValueError):
        JudgeBudgetConfig(enabled=True, cap=0)


def test_cost_per_call_must_be_positive() -> None:
    with pytest.raises(ValueError):
        JudgeBudgetConfig(enabled=True, cap=1.0, cost_per_call=0)


def test_cap_required_when_enabled_at_config_level() -> None:
    # Pydantic model validator fails fast at parse time.
    with pytest.raises(ValueError, match="cap must be set"):
        JudgeBudgetConfig(enabled=True)


def test_disabled_without_cap_is_valid() -> None:
    # Disabled budgets don't require a cap.
    cfg = JudgeBudgetConfig(enabled=False)
    assert cfg.cap is None


def test_build_guard_when_cap_missing() -> None:
    # Defense-in-depth: bypass validation via model_construct and confirm the
    # builder still refuses a capless enabled budget.
    bad = JudgeBudgetConfig.model_construct(enabled=True, cap=None, cost_per_call=1.0, on_exceeded="raise")
    with pytest.raises(ValueError, match="cap must be set"):
        build_budgeted_judge(MockJudge(), bad)


def test_invalid_on_exceeded_rejected_in_wrapper() -> None:
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


def test_engine_unwrapped_when_disabled() -> None:
    engine = EvalEngine.from_config(_engine_cfg())
    assert not isinstance(engine.judge, BudgetedJudge)


def test_engine_wrapped_when_enabled() -> None:
    engine = EvalEngine.from_config(_engine_cfg(judge_budget=_budget(cap=5.0)))
    assert isinstance(engine.judge, BudgetedJudge)


def test_attach_client_delegates_to_inner() -> None:
    class _Recorder(MockJudge):
        attached = None

        def attach_client(self, client):
            self.attached = client

    inner = _Recorder()
    j = build_budgeted_judge(inner, _budget(cap=1.0))
    assert isinstance(j, BudgetedJudge)
    j.attach_client("client-x")
    assert inner.attached == "client-x"


def test_engine_attaches_the_client_through_the_wrapper_to_the_inner_judge(monkeypatch) -> None:
    """The wrapper's `attach_client` must be *reachable*, not merely correct in isolation.

    `test_attach_client_delegates_to_inner` calls the wrapper directly, so it passed while
    the engine never invoked it: `from_config` attached to the raw judge and then replaced
    it with the wrapper. Coverage read 100% on a method production could not reach. This
    asserts the real path — engine → wrapper → inner — so the ordering cannot silently
    regress.

    The recorder is injected by patching `JUDGES.create` rather than registering a
    double, because a third test-double registration would perturb the public-surface and
    plugin-registry baselines and the matrix census.

    `mock.patch.object` rather than `monkeypatch.setattr`, and the difference is not
    stylistic. `create` lives on the *class*, so `monkeypatch` reads the inherited bound
    method as the "old value" and, on undo, writes it back as an INSTANCE attribute that
    outlives this test. Nothing here notices; but `JUDGES.create` then permanently shadows
    `Registry.create`, so any later class-level patch of `Registry.create` silently misses
    every judge. That is exactly how this residue defeated the M8 execution ledger
    (`tests/_m8_probe.py`) -- judge-backed pipelines scored correctly while the ledger
    recorded zero judge calls, and only when this module ran first. `mock.patch.object`
    records that the attribute was not local and `delattr`s on exit, leaving no shadow.
    `tests/_m8_probe.py::probe` now refuses to run if any registry carries one.
    """
    from eval_harness.plugins import JUDGES

    class _Recorder(MockJudge):
        def __init__(self):
            super().__init__()
            self.attached = None

        def attach_client(self, client):
            self.attached = client

    inner = _Recorder()

    # Spy on the WRAPPER. Asserting only that `inner` received the client cannot
    # distinguish the orderings — under the old one the engine attached to the raw judge
    # directly, so the inner assertion held while the wrapper was bypassed. Verified by
    # re-introducing the old ordering: an inner-only assertion still passed.
    through_wrapper: list[object] = []
    original = BudgetedJudge.attach_client

    def _spy(self, client):
        through_wrapper.append(client)
        return original(self, client)

    # `attach_client` IS local to BudgetedJudge, so monkeypatch restores it correctly;
    # only the inherited `JUDGES.create` needs `mock.patch.object` (see the docstring).
    monkeypatch.setattr(BudgetedJudge, "attach_client", _spy)

    from typing import cast

    from eval_harness.langfuse_client import LangfuseClient

    sentinel = cast(LangfuseClient, object())
    with patch.object(JUDGES, "create", lambda *a, **k: inner):
        engine = EvalEngine.from_config(_engine_cfg(judge_budget=_budget(cap=5.0)), langfuse_client=sentinel)

    assert "create" not in JUDGES.__dict__, (
        "patching JUDGES.create must leave no instance-level shadow of Registry.create; "
        "a shadow silently defeats every class-level patch, including tests/_m8_probe.py"
    )
    assert isinstance(engine.judge, BudgetedJudge), "precondition: the judge is wrapped"
    assert engine.judge._inner is inner
    assert through_wrapper == [sentinel], "the engine must attach through the wrapper, not around it"
    assert inner.attached is sentinel, "and the wrapper must delegate inward"


def test_attach_client_noop_when_inner_lacks_it() -> None:
    # MockJudge has no attach_client; wrapper must silently no-op (no crash).
    j = build_budgeted_judge(MockJudge(), _budget(cap=1.0))
    assert isinstance(j, BudgetedJudge)
    j.attach_client("ignored")  # should not raise
    assert j.evaluate("p").score == 1.0


# --------------------------------------------------------------------------
# F-030 — time-windowed rate limiting (additive on top of the cumulative cap)
# --------------------------------------------------------------------------


class _FakeClock:
    """Deterministic monotonic clock; ``sleep`` advances it (no real waiting)."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def sleep(self, secs: float) -> None:
        self.t += secs


def _rl_judge(clock, *, max_per_window=2, window_seconds=10.0, on_rate_limited="block", cap=1000.0):
    budget = _budget(
        cap=cap,
        max_per_window=max_per_window,
        window_seconds=window_seconds,
        on_rate_limited=on_rate_limited,
    )
    return build_budgeted_judge(MockJudge(default_score=1.0), budget, clock=clock, sleeper=clock.sleep)


def test_window_fields_must_be_set_together() -> None:
    with pytest.raises(ValueError, match="set together"):
        JudgeBudgetConfig(enabled=True, cap=1.0, max_per_window=5)  # missing window_seconds
    with pytest.raises(ValueError, match="set together"):
        JudgeBudgetConfig(enabled=True, cap=1.0, window_seconds=1.0)  # missing max_per_window


def test_invalid_on_rate_limited_rejected_at_config() -> None:
    with pytest.raises(ValueError, match="on_rate_limited"):
        JudgeBudgetConfig(enabled=True, cap=1.0, max_per_window=2, window_seconds=1.0, on_rate_limited="bogus")


def test_no_limiter_when_window_absent() -> None:
    j = build_budgeted_judge(MockJudge(), _budget(cap=5.0))
    assert isinstance(j, BudgetedJudge)
    assert j._limiter is None


def test_block_mode_throttles_then_admits_after_window() -> None:
    clock = _FakeClock()
    j = _rl_judge(clock, max_per_window=2, window_seconds=10.0)

    # Two calls fit the window with no waiting (clock stays at 0).
    j.evaluate("p")
    j.evaluate("p")
    assert clock.t == 0.0

    # Third call must wait for the oldest event to age out of the 10s window.
    j.evaluate("p")
    assert clock.t == 10.0  # slept exactly once, for the full window


def test_block_mode_recovers_without_sleep_once_window_passes() -> None:
    clock = _FakeClock()
    j = _rl_judge(clock, max_per_window=1, window_seconds=5.0)

    j.evaluate("p")  # admitted at t=0
    clock.t = 5.0  # caller's own time advances past the window
    j.evaluate("p")  # admitted with no sleep needed
    assert clock.t == 5.0


def test_skip_mode_returns_sentinel_when_rate_exceeded() -> None:
    clock = _FakeClock()
    j = _rl_judge(clock, max_per_window=2, window_seconds=10.0, on_rate_limited="skip")

    assert j.evaluate("p").score == 1.0
    assert j.evaluate("p").score == 1.0
    sentinel = j.evaluate("p")  # over the rate → skipped, no waiting
    assert "rate limit" in sentinel.reasoning
    assert clock.t == 0.0


def test_rate_limit_and_cap_are_independent() -> None:
    clock = _FakeClock()
    # Generous rate window but a hard cap of 2 calls.
    j = _rl_judge(clock, max_per_window=100, window_seconds=1.0, cap=2.0)
    j.evaluate("p")
    j.evaluate("p")
    with pytest.raises(BudgetExceededError):
        j.evaluate("p")  # cap trips even though the rate window has room


def test_invalid_on_rate_limited_rejected_in_wrapper() -> None:
    from agent_core import BudgetConfig, BudgetLedger, FrameworkConfig

    ledger = BudgetLedger(FrameworkConfig(budget=BudgetConfig(cap_units=1.0, reserve_fraction=0.0)))
    with pytest.raises(ValueError, match="on_rate_limited"):
        BudgetedJudge(MockJudge(), ledger, cost_per_call=1.0, on_rate_limited="nope")


def test_engine_wires_rate_limit_from_config() -> None:
    cfg = _engine_cfg(judge_budget=_budget(cap=5.0, max_per_window=3, window_seconds=2.0, on_rate_limited="skip"))
    engine = EvalEngine.from_config(cfg)
    assert isinstance(engine.judge, BudgetedJudge)
    assert engine.judge._limiter is not None


# --------------------------------------------------------------------------
# calls_per_evaluate — an inner judge (e.g. an N-member PanelJudge) that makes
# more than one provider call per evaluate() must charge N units, not 1, against
# both the cumulative cap and the rate window. Driven via _NCallMockJudge (a
# MockJudge subclass declaring calls_per_evaluate as a real field), so this file
# stays decoupled from eval_harness.judges.panel (PanelJudge's own tests own its
# aggregation logic) while staying mypy/ruff-clean (no dynamic setattr).
# --------------------------------------------------------------------------


class _NCallMockJudge(MockJudge):
    def __init__(self, calls_per_evaluate: int, default_score: float = 1.0):
        super().__init__(default_score=default_score)
        self.calls_per_evaluate = calls_per_evaluate


def test_calls_per_evaluate_defaults_to_one_for_a_plain_judge() -> None:
    j = build_budgeted_judge(MockJudge(), _budget(cap=1.0))
    assert isinstance(j, BudgetedJudge)
    assert j.calls_per_evaluate == 1


def test_calls_per_evaluate_is_read_duck_typed_from_inner() -> None:
    inner = _NCallMockJudge(calls_per_evaluate=3)
    j = build_budgeted_judge(inner, _budget(cap=1.0))
    assert isinstance(j, BudgetedJudge)
    assert j.calls_per_evaluate == 3


def test_cost_reservation_scales_by_calls_per_evaluate() -> None:
    inner = _NCallMockJudge(calls_per_evaluate=3, default_score=1.0)
    j = build_budgeted_judge(inner, _budget(cap=6.0, cost_per_call=1.0))
    assert isinstance(j, BudgetedJudge)
    j.evaluate("p")  # reserves 3
    assert j._ledger.spent == pytest.approx(3.0)
    j.evaluate("p")  # reserves 3 more -> exactly at the 6.0 cap
    assert j._ledger.spent == pytest.approx(6.0)
    with pytest.raises(BudgetExceededError):
        j.evaluate("p")  # a 3rd batch of 3 would overshoot the cap


def test_rate_limit_slots_scale_by_calls_per_evaluate() -> None:
    clock = _FakeClock()
    inner = _NCallMockJudge(calls_per_evaluate=3, default_score=1.0)
    budget = _budget(cap=1000.0, max_per_window=3, window_seconds=10.0)
    j = build_budgeted_judge(inner, budget, clock=clock, sleeper=clock.sleep)

    j.evaluate("p")  # consumes all 3 slots in the window at once
    assert clock.t == 0.0
    j.evaluate("p")  # window is full; must wait a full 10s for the batch to age out
    assert clock.t == 10.0


def test_build_budgeted_judge_raises_when_calls_per_evaluate_exceeds_window() -> None:
    inner = _NCallMockJudge(calls_per_evaluate=5)
    budget = _budget(cap=100.0, max_per_window=3, window_seconds=10.0)
    with pytest.raises(ValueError, match="exceeds max_per_window"):
        build_budgeted_judge(inner, budget)


def test_build_budgeted_judge_allows_calls_per_evaluate_equal_to_window() -> None:
    inner = _NCallMockJudge(calls_per_evaluate=3, default_score=1.0)
    budget = _budget(cap=100.0, max_per_window=3, window_seconds=10.0)
    j = build_budgeted_judge(inner, budget)  # must not raise
    assert isinstance(j, BudgetedJudge)
    assert j.calls_per_evaluate == 3


def test_no_window_configured_skips_the_calls_per_evaluate_guard() -> None:
    # No max_per_window/window_seconds at all -> nothing to check against, and no limiter.
    inner = _NCallMockJudge(calls_per_evaluate=1000)
    j = build_budgeted_judge(inner, _budget(cap=100.0))
    assert isinstance(j, BudgetedJudge)
    assert j._limiter is None


# ---- _SlidingWindowLimiter direct tests: the atomic N-slot acquisition itself ----


def test_try_acquire_n_is_all_or_nothing() -> None:
    from eval_harness.agent_core_adapter import _SlidingWindowLimiter

    clock = _FakeClock()
    limiter = _SlidingWindowLimiter(3, 10.0, clock=clock, sleeper=clock.sleep)
    assert limiter.try_acquire_n(2) is True  # 2/3 used
    assert limiter.try_acquire_n(2) is False  # would need 4/3 -- refused, nothing recorded
    # Proof no partial reservation leaked from the refused call: exactly 1 more slot
    # is free, matching 2 used (not 4).
    assert limiter.try_acquire_n(1) is True  # 3/3 used
    assert limiter.try_acquire_n(1) is False  # genuinely full now


def test_acquire_blocking_n_waits_for_enough_slots_not_just_the_oldest_one() -> None:
    from eval_harness.agent_core_adapter import _SlidingWindowLimiter

    clock = _FakeClock()
    limiter = _SlidingWindowLimiter(3, 10.0, clock=clock, sleeper=clock.sleep)
    limiter.try_acquire_n(3)  # window full at t=0
    # Freeing only the single oldest event would not be enough for n=2 -- must wait
    # for the full window (all 3 recorded at t=0 age out together) before 2 fit.
    limiter.acquire_blocking_n(2)
    assert clock.t == 10.0


def test_acquire_blocking_n_raises_when_n_exceeds_window_capacity() -> None:
    from eval_harness.agent_core_adapter import _SlidingWindowLimiter

    clock = _FakeClock()
    limiter = _SlidingWindowLimiter(3, 10.0, clock=clock, sleeper=clock.sleep)
    with pytest.raises(ValueError, match="window capacity is only 3"):
        limiter.acquire_blocking_n(4)
