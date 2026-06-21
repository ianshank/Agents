"""Task-instance and suite models shared across domains.

A domain's instances are deliberately abstract: an instance presents a discrete
``solution_space`` (candidate work products) of which a subset is ``correct``.
This keeps the corpus deterministic and offline (no code execution / network) while
remaining a faithful "does the work product pass the tests" oracle target — the
property oracle is a pure predicate over ``(candidate, instance)``.

``difficulty`` modulates how often a skilled agent succeeds; the mutation engine
(Phase 4) perturbs it and the ``tool_available`` / ``noise`` knobs into distributions.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TaskInstance(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    instance_id: str
    domain: str
    difficulty: float = Field(default=0.0, ge=0.0, le=1.0)
    solution_space: tuple[str, ...] = Field(min_length=2)
    correct: tuple[str, ...] = Field(min_length=1)
    tool_available: bool = True
    noise: float = Field(default=0.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _correct_within_space(self) -> TaskInstance:
        space = set(self.solution_space)
        if not set(self.correct) <= space:
            raise ValueError("correct answers must be a subset of solution_space")
        if len(self.correct) >= len(self.solution_space):
            raise ValueError("at least one wrong answer must exist in solution_space")
        return self

    @property
    def wrong(self) -> tuple[str, ...]:
        correct = set(self.correct)
        return tuple(c for c in self.solution_space if c not in correct)


class TaskSuite(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    domain: str
    instances: tuple[TaskInstance, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _ids_unique_and_domain_consistent(self) -> TaskSuite:
        ids = [i.instance_id for i in self.instances]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate instance_id in suite")
        if any(i.domain != self.domain for i in self.instances):
            raise ValueError("all instances must share the suite domain")
        return self

    def __len__(self) -> int:
        return len(self.instances)
