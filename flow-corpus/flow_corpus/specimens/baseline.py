# pyright: reportMissingImports=false
"""Baseline single-agent specimen — the mandatory control.

One policy query, reported verbatim. The simplest flow shape; every richer flow is
measured against this control. Its confidence is the policy's raw self-report.
"""

from __future__ import annotations

import random

from flow_protocol import FlowResult

from flow_corpus.suites.base import TaskInstance

from .base import SpecimenBase


class BaselineSpecimen(SpecimenBase):
    flow_type = "baseline"
    impl_version = "1"

    def run(self, instance: TaskInstance, rng: random.Random) -> FlowResult:
        decision = self.policy.decide(instance, rng)
        return self._result(instance, decision.candidate, decision.confidence, seed=None)
