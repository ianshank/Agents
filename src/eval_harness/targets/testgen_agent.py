"""Agent-in-the-loop test-generation pipeline (Deck B).

A registered ``TargetRunner`` that generates a suite from focal method +
obligations, then executes it through :func:`run_generated_suite` so the existing
F-065 scorers read the same ``TESTGEN_EVIDENCE_KEY`` payload as Deck A+.

The generator **never sees** ``inputs.suite``. A generator whose only trick is
copying the corpus suite cannot grade its own homework. That strip happens on a
copy; the original item is not mutated.

This is **not** an ADR 0039 callable path. The pipeline is selected by registry
name (``type: testgen_agent``), the same shape as ``rca_maxz`` /
``provenance_recorder``. ADR 0039 applies only when ``generator_path`` names a
``module:attr`` to import. Never allowlist ``eval_harness``.

A missing generator, a malformed/empty suite, or a split outside
``allowed_splits`` fail closed with structured empty evidence (ADR 0038) rather
than raising.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from ..core._imports import import_allowed_module, resolve_allowed_attribute
from ..core.interfaces import TargetRunner
from ..core.types import TESTGEN_EVIDENCE_KEY, EvalItem, TargetOutput
from ..plugins import TARGETS
from .testgen import _empty_evidence, run_generated_suite

logger = logging.getLogger(__name__)

#: Keys removed from the copy the generator is allowed to see.
_STRIPPED_INPUT_KEYS = frozenset({"suite"})

#: Default split membership the Deck B profile evaluates. Train items fail closed
#: so a job cannot iterate on sequestered holdout by pointing the dataset at the
#: thorough slice and ignoring ``metadata.split``.
_DEFAULT_ALLOWED_SPLITS: tuple[str, ...] = ("holdout",)

#: How many hex characters of sha256 to keep on attempt / prompt / suite hashes.
_DEFAULT_DIGEST_CHARS = 16

#: Held-constant preamble. Not a ``str.format`` template: focal source can contain
#: braces, and formatting untrusted code is how a prompt silently drops.
_DEFAULT_PROMPT_PREAMBLE = (
    "Write a pytest module that imports the focal method from `focal` and "
    "asserts the behaviour the obligations require."
)

#: Metadata keys added beside the F-065 evidence payload (additive; scorers ignore them).
ATTEMPT_ID_KEY = "testgen_attempt_id"
PROMPT_HASH_KEY = "testgen_prompt_hash"
SUITE_HASH_KEY = "testgen_suite_hash"

GeneratorFn = Callable[..., object]


@dataclass(frozen=True)
class TestgenAgentConfig:
    """Operator knobs for :class:`TestgenAgentTarget`. Defaults live here, not at call sites."""

    __test__ = False

    allowed_splits: tuple[str, ...] = _DEFAULT_ALLOWED_SPLITS
    """Item ``metadata.split`` values the pipeline will generate for. Deck B is holdout."""

    prompt_preamble: str = _DEFAULT_PROMPT_PREAMBLE
    """Constant prefix hashed into ``testgen_prompt_hash``. Not tuned per holdout item."""

    digest_chars: int = _DEFAULT_DIGEST_CHARS
    """Hex characters kept from sha256 digests written into additive metadata."""

    def __post_init__(self) -> None:
        if not math.isfinite(self.digest_chars) or int(self.digest_chars) != self.digest_chars:
            raise ValueError(f"digest_chars must be a finite integer, got {self.digest_chars!r}")
        if not 8 <= int(self.digest_chars) <= 64:
            raise ValueError(f"digest_chars must be in [8, 64], got {self.digest_chars!r}")
        object.__setattr__(self, "digest_chars", int(self.digest_chars))
        cleaned = tuple(str(s) for s in self.allowed_splits if str(s))
        object.__setattr__(self, "allowed_splits", cleaned)


def _split_of(item: EvalItem) -> str | None:
    raw = item.metadata.get("split") if isinstance(item.metadata, dict) else None
    if raw is None:
        return None
    return str(raw)


def _empty_for(item: EvalItem) -> dict[str, Any]:
    mutants = item.inputs.get("mutants") if isinstance(item.inputs, dict) else None
    listed = list(mutants) if isinstance(mutants, list) else []
    return _empty_evidence(listed, timed_out=False)


def _generator_view(item: EvalItem) -> EvalItem:
    """Copy of *item* whose inputs do not contain ``suite``."""
    raw = item.inputs if isinstance(item.inputs, dict) else {}
    return EvalItem(
        id=item.id,
        inputs={k: v for k, v in raw.items() if k not in _STRIPPED_INPUT_KEYS},
        expected=item.expected,
        metadata=dict(item.metadata) if isinstance(item.metadata, dict) else {},
    )


def _prompt_material(preamble: str, view: EvalItem) -> str:
    """Canonical prompt bytes: constant preamble plus the fields the generator may see."""
    inputs = view.inputs
    payload = {
        "focal_name": inputs.get("focal_name"),
        "reference": inputs.get("reference"),
        "obligations": inputs.get("obligations"),
    }
    return preamble + "\n" + json.dumps(payload, sort_keys=True, default=str)


def _digest(text: str, chars: int) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:chars]


@TARGETS.register("testgen_agent", aliases=("testgen-agent",))
class TestgenAgentTarget(TargetRunner):
    """Generate a suite (DI fake or allowlisted path), then execute it in-process."""

    __test__ = False

    def __init__(
        self,
        generate: GeneratorFn | None = None,
        generator_path: str | None = None,
        allowed_splits: Sequence[str] | None = None,
        prompt_preamble: str | None = None,
        digest_chars: int | None = None,
    ) -> None:
        if generate is not None and generator_path:
            raise ValueError("testgen_agent takes generate= or generator_path=, not both")
        self._config = TestgenAgentConfig(
            allowed_splits=(tuple(allowed_splits) if allowed_splits is not None else _DEFAULT_ALLOWED_SPLITS),
            prompt_preamble=(prompt_preamble if prompt_preamble is not None else _DEFAULT_PROMPT_PREAMBLE),
            digest_chars=_DEFAULT_DIGEST_CHARS if digest_chars is None else digest_chars,
        )
        self._generate = generate
        self._generator_path = generator_path
        self._resolved: GeneratorFn | None = None

    def is_deterministic(self) -> bool | None:
        """Injected fakes and the missing-generator path are constant; a path is unknown."""
        if self._generator_path:
            return None
        return True

    def _resolve_generator(self) -> GeneratorFn | None:
        if self._generate is not None:
            return self._generate
        if not self._generator_path:
            return None
        if self._resolved is None:
            module_name, _, attr = self._generator_path.partition(":")
            if not attr:
                raise ValueError(f"generator_path {self._generator_path!r} must be 'module:function'")
            module = import_allowed_module(module_name)
            fn = resolve_allowed_attribute(module, attr)
            if not callable(fn):
                raise TypeError(f"generator_path {self._generator_path!r} did not resolve to a callable")
            self._resolved = fn
        return self._resolved

    def _fail(self, item: EvalItem, error: str, extra: dict[str, Any] | None = None) -> TargetOutput:
        metadata: dict[str, Any] = {TESTGEN_EVIDENCE_KEY: _empty_for(item)}
        if extra:
            metadata.update(extra)
        logger.warning("testgen_agent: %s for %s", error, item.id)
        return TargetOutput(output=None, error=error, metadata=metadata)

    def _invoke(self, fn: GeneratorFn, view: EvalItem) -> object:
        try:
            return fn(view)
        except TypeError:
            return fn(view.inputs)

    def run(self, item: EvalItem) -> TargetOutput:
        if not isinstance(item.inputs, dict):
            return self._fail(item, "item.inputs must be a mapping")

        split = _split_of(item)
        if split is None:
            return self._fail(item, "item is missing metadata.split")
        if split not in self._config.allowed_splits:
            return self._fail(
                item,
                f"item split {split!r} is outside allowed_splits {list(self._config.allowed_splits)}",
            )

        try:
            generator = self._resolve_generator()
        except Exception as exc:
            return self._fail(item, f"generator_path could not be resolved: {exc}")

        view = _generator_view(item)
        prompt = _prompt_material(self._config.prompt_preamble, view)
        prompt_hash = _digest(prompt, self._config.digest_chars)
        extra = {PROMPT_HASH_KEY: prompt_hash}

        if generator is None:
            return self._fail(
                item,
                "no generator configured (inject generate= or set generator_path)",
                extra,
            )

        try:
            produced = self._invoke(generator, view)
        except Exception as exc:
            return self._fail(item, f"generator raised: {exc}", extra)

        if not isinstance(produced, str) or not produced.strip():
            return self._fail(item, "generator returned a malformed or empty suite", extra)

        suite_hash = _digest(produced, self._config.digest_chars)
        extra[SUITE_HASH_KEY] = suite_hash
        extra[ATTEMPT_ID_KEY] = _digest(f"{item.id}:{prompt_hash}", self._config.digest_chars)

        payload = dict(item.inputs)
        payload["suite"] = produced
        executed = run_generated_suite(payload)
        metadata = dict(executed.metadata or {})
        metadata.update(extra)
        return TargetOutput(
            output=executed.output,
            latency_ms=executed.latency_ms,
            error=executed.error,
            metadata=metadata,
            trajectory=executed.trajectory,
        )
