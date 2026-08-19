"""Pairwise, order-swapped calibration corpus for judge bias probes.

Not :class:`~agent_core.golden.GoldenItem`: that type is binary-label
``(item_id, text, label ∈ {0,1})`` for the merge gate, with no notion of an
answer *pair*. A judge-bias corpus needs two candidate answers, their model
families, and (optionally) a known-correct winner — a distinct shape, not a
generalisation of the golden set.

Mirrors :mod:`agent_core.golden`'s container conventions (duplicate-id
rejection, order-independent equality, deterministic JSONL round-trip) so the
two corpus types stay familiar to a reader of one after the other.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from .config import ConfigError

#: The three canary kinds a corpus may tag an item with — pairs whose correct
#: verdict is known by construction, so a judge that stops discriminating at
#: all is caught rather than scoring a flattering agreement rate on an easy
#: corpus (design.md).
_CANARY_KINDS = ("known_equal", "clearly_better", "clearly_worse")
_VERDICTS = ("a", "b", "tie")


@dataclass(frozen=True)
class PairwiseItem:
    item_id: str
    prompt: str
    answer_a: str
    answer_b: str
    family_a: str
    family_b: str
    expected: str | None = None  # "a" | "b" | "tie" | None (no ground truth)
    domain: str = "default"
    source: str = ""
    canary_kind: str | None = None  # "known_equal" | "clearly_better" | "clearly_worse" | None
    meta: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.expected is not None and self.expected not in _VERDICTS:
            raise ValueError(
                f"PairwiseItem.expected must be 'a', 'b', 'tie' or None, got {self.expected!r}"
            )
        if self.canary_kind is None:
            return
        if self.canary_kind not in _CANARY_KINDS:
            raise ValueError(
                f"PairwiseItem.canary_kind must be one of {_CANARY_KINDS} or None"
                f", got {self.canary_kind!r}"
            )
        if self.canary_kind == "known_equal" and self.expected != "tie":
            raise ValueError("PairwiseItem: canary_kind='known_equal' requires expected='tie'")
        if self.canary_kind in ("clearly_better", "clearly_worse") and self.expected not in (
            "a",
            "b",
        ):
            raise ValueError(
                f"PairwiseItem: canary_kind={self.canary_kind!r} requires expected in ('a', 'b')"
            )

    def __hash__(self) -> int:
        # meta dict is unhashable; hash on stable fields only (mirrors GoldenItem).
        return hash(
            (
                self.item_id,
                self.prompt,
                self.answer_a,
                self.answer_b,
                self.family_a,
                self.family_b,
                self.expected,
                self.domain,
                self.source,
                self.canary_kind,
            )
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PairwiseItem):
            return NotImplemented
        return (
            self.item_id == other.item_id
            and self.prompt == other.prompt
            and self.answer_a == other.answer_a
            and self.answer_b == other.answer_b
            and self.family_a == other.family_a
            and self.family_b == other.family_b
            and self.expected == other.expected
            and self.domain == other.domain
            and self.source == other.source
            and self.canary_kind == other.canary_kind
            and self.meta == other.meta
        )


@dataclass(frozen=True, eq=False)
class PairwiseSet:
    items: tuple[PairwiseItem, ...]

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for item in self.items:
            if item.item_id in seen:
                raise ConfigError(f"duplicate item_id in PairwiseSet: {item.item_id!r}")
            seen.add(item.item_id)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PairwiseSet):
            return NotImplemented
        # order-independent: PairwiseSet is a set of items, not an ordered sequence
        return frozenset(self.items) == frozenset(other.items)

    def __hash__(self) -> int:
        return hash(frozenset(self.items))

    @property
    def canaries(self) -> tuple[PairwiseItem, ...]:
        return tuple(i for i in self.items if i.canary_kind is not None)

    def to_jsonl(self) -> str:
        """Deterministic JSONL: rows sorted by item_id, each row sort_keys=True."""
        rows = sorted(self.items, key=lambda x: x.item_id)
        lines = [json.dumps(asdict(item), sort_keys=True) for item in rows]
        return "\n".join(lines) + "\n"

    @classmethod
    def from_jsonl(cls, text: str) -> PairwiseSet:
        items: list[PairwiseItem] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            items.append(
                PairwiseItem(
                    item_id=str(d["item_id"]),
                    prompt=str(d["prompt"]),
                    answer_a=str(d["answer_a"]),
                    answer_b=str(d["answer_b"]),
                    family_a=str(d["family_a"]),
                    family_b=str(d["family_b"]),
                    expected=d.get("expected"),
                    domain=str(d.get("domain", "default")),
                    source=str(d.get("source", "")),
                    canary_kind=d.get("canary_kind"),
                    meta={str(k): str(v) for k, v in d.get("meta", {}).items()},
                )
            )
        return cls(tuple(items))
