"""Canonicalization of tool calls, so trajectories compare deterministically.

Lives in ``core`` (which depends on nothing) alongside ``_serialize``, and is pure:
no I/O, no clock, no RNG, no SDK imports. Scorers stay pure per-item maps and this
module is what lets them be — ``docs/CHARTER.md`` §4 invariant 4.

Properties this module guarantees, each with a test that pins it:

* **Name canonicalization.** ``Search`` and ``search`` are the same tool.
* **Argument canonicalization.** Two calls whose argument mappings differ only by key
  insertion order are the same call. Applied recursively, so nesting depth is irrelevant.
* **Set canonicalization.** Sets and frozensets are order-insensitive *in Python* but
  their iteration order varies with ``PYTHONHASHSEED``, so they are normalized to a
  sorted-by-canonical-representation list. Without this, the same trajectory canonicalizes
  differently in different processes (F-051 review finding).
* **Stable rendering of unknown types.** Objects JSON cannot serialize are rendered by
  *type name*, never ``str()`` — ``str(object())`` embeds a memory address, which would
  make the canonical form differ on every run (F-051 review finding).
* **Duplicate preservation.** Repeated calls are never collapsed. A duplicate *is* the
  signal for precision and loop scoring, so comparisons operate on multisets, not sets.
* **Bounded recursion.** Nesting deeper than ``max_depth`` is truncated to a marker rather
  than raising ``RecursionError``, which the engine would otherwise convert into a *failing*
  verdict for what is really an unscoreable input.

Volatile fields (request ids, timestamps) can be dropped via ``ignore_fields`` before
comparison, at any nesting depth.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping, Sequence, Set
from dataclasses import dataclass, field
from typing import Any

from .types import ToolCallRecord

logger = logging.getLogger(__name__)

#: Canonical form of one tool call: ``(name, stable-json-of-arguments)``. Hashable, so
#: it drops straight into a ``Counter`` for multiset comparison.
CanonicalCall = tuple[str, str]

#: Emitted in place of a subtree deeper than ``NormalizationConfig.max_depth``. A constant
#: rather than an inline literal so callers can detect truncation without matching a string.
TRUNCATED = "<truncated:max-depth>"


class DepthLimitError(ValueError):
    """Raised when argument nesting exceeds ``NormalizationConfig.max_depth``.

    Callers that would rather report "cannot score this" than a failing verdict catch this
    and return a not-applicable result. Distinct from ``RecursionError`` so it can be caught
    narrowly, and a subclass of ``ValueError`` so it reads as bad input rather than a bug.
    """


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

    max_depth: int = 50
    """Maximum argument nesting depth. Real tool arguments are shallow; anything deeper is
    treated as unscoreable rather than allowed to hit Python's recursion limit. Generous by
    default so it never fires on legitimate input."""

    truncate_over_max_depth: bool = False
    """When True, a too-deep subtree becomes :data:`TRUNCATED` and comparison continues.
    When False (default), :class:`DepthLimitError` is raised so the caller can report a
    not-applicable verdict instead of silently comparing truncated data."""

    def __post_init__(self) -> None:
        if self.max_depth < 1:
            raise ValueError(f"max_depth must be >= 1; got {self.max_depth}")


def _stable_repr(value: Any) -> str:
    """Render a value JSON cannot serialize, deterministically and type-distinguishably.

    Always ``"<QualName:payload>"``. Two properties have to hold at once, and the obvious
    implementations each sacrifice one:

    * **Deterministic.** ``json.dumps(..., default=str)`` fails here — ``str(object())`` is
      ``"<object object at 0x7f...>"``, so the canonical form embeds a memory address and
      changes every run. Addresses are therefore dropped in favour of the type name.
    * **Type-distinguishing.** Rendering *only* the type name fails the other way: two
      unrelated classes whose ``__str__`` both return ``"X"`` would canonicalize equal.

    Emitting both keeps ``Decimal("1.50")`` distinguishable by value *and* distinguishable
    from a ``str`` that happens to read ``"1.50"``. The payload is dropped only when it is
    an address, which carries no value information.
    """
    qualname = type(value).__qualname__
    if isinstance(value, (bytes, bytearray)):
        return f"<{qualname}:len={len(value)}>"
    text = str(value)
    # A default __repr__/__str__ renders as "<... at 0x...>"; that payload is identity, not
    # value, so the type name alone is the whole stable signal.
    if " at 0x" in text or " object at " in text:
        return f"<{type(value).__module__}.{qualname}>"
    return f"<{qualname}:{text}>"


def normalize_name(name: str, config: NormalizationConfig) -> str:
    """Canonicalize a tool name under *config*."""
    result = name.strip() if config.strip_names else name
    return result if config.case_sensitive_names else result.lower()


def normalize_arguments(value: Any, config: NormalizationConfig, _depth: int = 0) -> Any:
    """Recursively canonicalize an argument value.

    Mappings have ignored keys removed and are rebuilt with sorted keys; sequences keep
    their order (argument order is meaningful) but have their elements canonicalized; sets
    are sorted by canonical representation because their iteration order is not stable
    across processes; scalars pass through. Strings and bytes are treated as scalars, not
    sequences.
    """
    if _depth >= config.max_depth:
        if config.truncate_over_max_depth:
            logger.debug("normalization truncated a subtree at depth %d", _depth)
            return TRUNCATED
        raise DepthLimitError(f"argument nesting exceeded max_depth={config.max_depth}")
    if isinstance(value, Mapping):
        return {
            key: normalize_arguments(item, config, _depth + 1)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if key not in config.ignore_fields
        }
    if isinstance(value, (str, bytes, bytearray)):
        return value if isinstance(value, str) else _stable_repr(value)
    if isinstance(value, Set):
        # Sorted by the canonical JSON of each element, so ordering is a pure function of
        # the *values* rather than of this process's hash seed.
        normalized = [normalize_arguments(item, config, _depth + 1) for item in value]
        return sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True, default=_stable_repr))
    if isinstance(value, Sequence):
        return [normalize_arguments(item, config, _depth + 1) for item in value]
    return value


def canonical_call(call: ToolCallRecord, config: NormalizationConfig) -> CanonicalCall:
    """Reduce a tool call to its hashable canonical form.

    ``call_id`` is deliberately excluded: it is a provider correlation id, not part of
    what the agent did, and including it would make every trajectory unique.

    Raises :class:`DepthLimitError` when arguments nest deeper than ``max_depth`` and
    ``truncate_over_max_depth`` is False.
    """
    if not config.compare_arguments:
        return (normalize_name(call.name, config), "")
    normalized = normalize_arguments(dict(call.arguments), config)
    return (
        normalize_name(call.name, config),
        json.dumps(normalized, sort_keys=True, default=_stable_repr),
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
