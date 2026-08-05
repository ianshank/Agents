"""Canonicalization of tool calls, so trajectories compare deterministically.

Lives in ``core`` (which depends on nothing) alongside ``_serialize``, and is pure:
no I/O, no clock, no RNG, no SDK imports. Scorers stay pure per-item maps and this
module is what lets them be — ``docs/CHARTER.md`` §4 invariant 4.

Three properties this module exists to guarantee:

* **Name canonicalization.** ``Search`` and ``search`` are the same tool.
* **Argument canonicalization.** Two calls whose argument mappings differ only by key
  insertion order are the same call. Applied recursively, so nesting depth is irrelevant.
* **Duplicate preservation.** Repeated calls are never collapsed. A duplicate *is* the
  signal for precision and loop scoring, so comparisons operate on multisets, not sets.

Volatile fields (request ids, timestamps) can be dropped via ``ignore_fields`` before
comparison, at any nesting depth.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .types import ToolCallRecord

#: Canonical form of one tool call: ``(name, stable-json-of-arguments)``. Hashable, so
#: it drops straight into a ``Counter`` for multiset comparison.
CanonicalCall = tuple[str, str]


@dataclass(frozen=True)
class NormalizationConfig:
    """How tool calls are canonicalized before they are compared.

    Every knob is a field with a documented default, so nothing numeric or behavioural
    sits at a call site (``docs/CHARTER.md`` §4 invariant 5).
    """

    case_sensitive_names: bool = False
    """When False (default), tool names compare case-insensitively."""

    strip_names: bool = True
    """Strip surrounding whitespace from tool names before comparing."""

    ignore_fields: frozenset[str] = field(default_factory=frozenset)
    """Argument keys dropped before comparison, at any nesting depth. Use for volatile
    values such as request ids and timestamps that differ run to run without carrying
    behavioural meaning."""

    compare_arguments: bool = True
    """When False, only tool *names* are compared — useful for suites that care which
    tools were reached but not how they were parameterized."""


def normalize_name(name: str, config: NormalizationConfig) -> str:
    """Canonicalize a tool name under *config*."""
    result = name.strip() if config.strip_names else name
    return result if config.case_sensitive_names else result.lower()


def normalize_arguments(value: Any, config: NormalizationConfig) -> Any:
    """Recursively canonicalize an argument value.

    Mappings have ignored keys removed and are rebuilt with sorted keys; sequences keep
    their order (argument order is meaningful) but have their elements canonicalized;
    scalars pass through. Strings and bytes are treated as scalars, not sequences.
    """
    if isinstance(value, Mapping):
        return {
            key: normalize_arguments(item, config)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if key not in config.ignore_fields
        }
    if isinstance(value, (str, bytes)):
        return value
    if isinstance(value, Sequence):
        return [normalize_arguments(item, config) for item in value]
    return value


def canonical_call(call: ToolCallRecord, config: NormalizationConfig) -> CanonicalCall:
    """Reduce a tool call to its hashable canonical form.

    ``call_id`` is deliberately excluded: it is a provider correlation id, not part of
    what the agent did, and including it would make every trajectory unique.
    """
    if not config.compare_arguments:
        return (normalize_name(call.name, config), "")
    normalized = normalize_arguments(dict(call.arguments), config)
    return (
        normalize_name(call.name, config),
        json.dumps(normalized, sort_keys=True, default=str),
    )


def canonical_calls(
    calls: Iterable[ToolCallRecord],
    config: NormalizationConfig,
) -> tuple[CanonicalCall, ...]:
    """Canonicalize a sequence of calls, preserving order *and* duplicates."""
    return tuple(canonical_call(call, config) for call in calls)


def is_subsequence(reference: Sequence[Any], candidate: Sequence[Any]) -> bool:
    """Whether every element of *reference* appears in *candidate* in the same order.

    Extra elements in *candidate* are tolerated; this is the in-order matching rule.
    Greedy scanning is correct here because each reference element is matched against
    the earliest remaining candidate element, and matching earlier never rules out a
    later match that a deferred choice would have allowed.
    """
    remaining = iter(candidate)
    return all(any(item == expected for item in remaining) for expected in reference)
