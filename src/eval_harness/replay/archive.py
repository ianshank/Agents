"""Append-only JSONL archive of replay envelopes, confined by DATA_ROOT / OUTPUT_ROOT."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path

from ..core._paths import DATA_ROOT_ENV, OUTPUT_ROOT_ENV, resolve_confined_path
from .envelope import ReplayEnvelope, ReplayError, envelope_from_dict, envelope_to_dict


class ReplayArchive:
    """One JSONL file, one envelope per line. Duplicate ``item_id``: last write wins."""

    def __init__(self, path: str | Path, *, for_write: bool = False) -> None:
        self._raw = str(path)
        self._for_write = for_write
        self.path = resolve_confined_path(
            path,
            root_env_var=OUTPUT_ROOT_ENV if for_write else DATA_ROOT_ENV,
            description="replay archive path",
            must_exist=not for_write,
        )

    def load(self) -> tuple[ReplayEnvelope, ...]:
        """Read every envelope. A corrupt line fails closed (does not skip)."""
        envelopes: list[ReplayEnvelope] = []
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ReplayError(f"could not read replay archive {self.path}: {exc}") from exc
        for line_no, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                raw = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ReplayError(f"corrupt JSONL at {self.path}:{line_no}: {exc}") from exc
            try:
                envelopes.append(envelope_from_dict(raw))
            except ReplayError as exc:
                raise ReplayError(f"invalid envelope at {self.path}:{line_no}: {exc}") from exc
        return tuple(envelopes)

    def by_item_id(self) -> Mapping[str, ReplayEnvelope]:
        """Index by ``item_id``; later lines overwrite earlier ones."""
        index: dict[str, ReplayEnvelope] = {}
        for envelope in self.load():
            index[envelope.item_id] = envelope
        return index

    def append(self, envelopes: Iterable[ReplayEnvelope]) -> None:
        """Append envelopes. Parent directories are created when missing."""
        if not self._for_write:
            raise ReplayError("archive opened for read cannot append")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            for envelope in envelopes:
                handle.write(json.dumps(envelope_to_dict(envelope), sort_keys=True) + "\n")
