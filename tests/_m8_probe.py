"""Execution ledger for M8 composability: proof a component's protocol method RAN.

Before this module, M8 credited a registered component for appearing in a validated
``EvalConfig`` dict -- ``pipeline_kinds()`` (``tests/_matrix_coverage.py``) reads typed
config fields and records the component names it finds. Nothing observed execution, so a
pipeline could name a component it never invoked and still be credited for composing it.
That was not hypothetical: ``PIPELINES["echo_exact_match"]`` declared
``judge: {"type": "mock"}`` while its only scorers (``exact_match``, ``contains``) are not
judge-backed, so ``MockJudge.evaluate`` ran zero times and the matrix said otherwise.

The ledger patches :meth:`Registry.create` -- the single construction choke point every
registered component of all six kinds passes through (``core/registry.py``) -- and wraps each
constructed instance's protocol method with a counter. Because it hooks construction rather
than any one call site, components built *inside* other components are credited without
their own instrumentation: ``PanelJudge``'s member judges (``judges/panel.py``, via
``JUDGES.create``) and ``CompositeScorer``'s child scorers (``scorers/__init__.py``, via
``SCORERS.create``) both route through the same seam real usage does.

Deliberately test-only: this lives under ``tests/`` beside ``_matrix_coverage.py`` and
``_e2e_matrix.py`` (the underscore-prefixed policy/support-module convention), and no
production code imports or knows about it.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

from eval_harness.core.interfaces import (
    DatasetSource,
    Judge,
    ResultSink,
    Scorer,
    StateAdapter,
    TargetRunner,
)
from eval_harness.core.registry import Registry

#: ``kind -> protocol method names whose execution counts as "this component ran"``.
#:
#: A *checked* declaration, not a free-standing list: the loop below cross-checks every
#: entry against the live Protocol at import time, so renaming e.g. ``Judge.evaluate``
#: fails here loudly instead of silently under-counting forever. This is ADR 0032 rule 2
#: ("a literal cross-checked against reality is a checked declaration") applied to method
#: names rather than component names.
#:
#: ``state_adapter`` tracks all three lifecycle methods, not one: the engine brackets an
#: attempt ``reset -> snapshot -> ... -> snapshot -> evaluate``, and an adapter that only
#: had ``reset`` called has not meaningfully participated in the run.
_PROTOCOL_METHODS: dict[str, tuple[str, ...]] = {
    "scorer": ("score",),
    "dataset": ("load",),
    "target": ("run",),
    "judge": ("evaluate",),
    "sink": ("emit",),
    "state_adapter": ("snapshot", "evaluate", "reset"),
}

#: The live Protocols the map above is validated against. Keyed by the same registry
#: ``kind`` strings ``plugins.py`` constructs its registries with.
_PROTOCOLS: dict[str, type] = {
    "scorer": Scorer,
    "dataset": DatasetSource,
    "target": TargetRunner,
    "judge": Judge,
    "sink": ResultSink,
    "state_adapter": StateAdapter,
}


def _validate_protocol_methods() -> None:
    """Fail at import if ``_PROTOCOL_METHODS`` names a method a Protocol does not have.

    Extracted from module scope so the check is callable from a test (proving the guard
    itself can fail) rather than only observable as an import side effect.
    """
    missing_kinds = set(_PROTOCOL_METHODS) ^ set(_PROTOCOLS)
    if missing_kinds:
        raise AssertionError(f"_PROTOCOL_METHODS and _PROTOCOLS disagree on kinds: {sorted(missing_kinds)}")
    for kind, methods in _PROTOCOL_METHODS.items():
        protocol = _PROTOCOLS[kind]
        for method in methods:
            if not callable(getattr(protocol, method, None)):
                raise AssertionError(
                    f"_PROTOCOL_METHODS[{kind!r}] names {method!r}, which is not a callable "
                    f"attribute of {protocol.__name__} -- this map is a checked declaration; "
                    "update it to match the Protocol."
                )


_validate_protocol_methods()


class ExecutionLedger:
    """Records which ``(kind, canonical component, method)`` triples actually executed."""

    def __init__(self) -> None:
        self._calls: Counter[tuple[str, str, str]] = Counter()

    def wrap(self, instance: Any, *, kind: str, component: str) -> None:
        """Wrap *instance*'s tracked protocol methods with counting proxies.

        Patched on the INSTANCE, not its class, so two instances of the same type are
        counted independently -- a ``PanelJudge`` built from two ``mock`` members must not
        have one member's call attributed to the other, and a class-level patch could not
        tell them apart.

        A component missing a tracked method is skipped rather than raising: a partial test
        double is a legitimate thing to construct, and the ledger's job is to observe, never
        to constrain what may be built.
        """
        for method_name in _PROTOCOL_METHODS[kind]:
            original = getattr(instance, method_name, None)
            if original is None:
                continue
            key = (kind, component, method_name)

            def _counted(
                *args: Any,
                __original: Any = original,
                __key: tuple[str, str, str] = key,
                **kwargs: Any,
            ) -> Any:
                self._calls[__key] += 1
                return __original(*args, **kwargs)

            object.__setattr__(instance, method_name, _counted)

    def call_count(self, kind: str, component: str, method: str) -> int:
        """How many times one tracked method ran on *component*."""
        return self._calls[(kind, component, method)]

    def invoked(self, kind: str, component: str) -> bool:
        """True iff EVERY method tracked for *kind* ran at least once on *component*.

        The conjunction matters for ``state_adapter``: an adapter whose ``reset`` ran but
        whose ``evaluate`` never did has not been composed in any sense worth crediting.
        """
        return all(self._calls[(kind, component, method)] > 0 for method in _PROTOCOL_METHODS[kind])

    def invoked_components(self) -> dict[str, set[str]]:
        """``kind -> {components fully invoked}``, the executed side of the vacuity diff."""
        candidates = {(kind, component) for (kind, component, _method) in self._calls}
        executed: dict[str, set[str]] = {}
        for kind, component in sorted(candidates):
            if self.invoked(kind, component):
                executed.setdefault(kind, set()).add(component)
        return executed


@contextmanager
def probe() -> Iterator[ExecutionLedger]:
    """Patch :meth:`Registry.create` for the block, wrapping everything it constructs.

    The wrapper preserves ``create``'s real signature, ``params`` default included. That
    default is load-bearing rather than cosmetic: ``Registry.create(name)`` is called with
    no ``params`` argument in the wild (``tests/test_registry.py``), so a wrapper declaring
    ``params`` positional-required raises ``TypeError`` for that call the moment any probe
    is active -- breaking a test that has nothing to do with the matrix.

    An unknown registry kind raises rather than being silently ignored: a seventh registry
    added to ``plugins.py`` must extend ``_PROTOCOL_METHODS`` deliberately, exactly as
    ``STATE_ADAPTERS`` had to extend the matrix policy when it landed.
    """
    ledger = ExecutionLedger()
    original_create = Registry.create

    def patched_create(self: Registry[Any], name: str, params: dict[str, Any] | None = None) -> Any:
        instance = original_create(self, name, params)
        if self.kind not in _PROTOCOL_METHODS:
            raise AssertionError(
                f"probe(): registry kind {self.kind!r} has no _PROTOCOL_METHODS entry -- a new "
                "registry kind was added; extend that checked declaration so its components "
                "can be credited for execution."
            )
        ledger.wrap(instance, kind=self.kind, component=self.resolve(name))
        return instance

    with patch.object(Registry, "create", patched_create):
        yield ledger
