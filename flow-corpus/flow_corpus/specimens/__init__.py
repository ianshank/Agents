"""Specimen library: flow variants under test, and a small self-registration registry.

The registry mirrors the harness's ``eval_harness.core.registry`` pattern but is
re-implemented here (≈ a dozen lines) so the corpus shares no code with the harness
beyond ``flow_protocol`` — keeping the airgap intact.
"""

from __future__ import annotations

from .base import Registry, Specimen, SpecimenBase
from .baseline import BaselineSpecimen
from .mcts import MCTSSpecimen
from .react import ReActSpecimen

# Specimen classes register here by name; config selects them without code edits.
# (Constructors differ — e.g. MCTS takes n_rollouts — so the registry holds the
# class, and callers instantiate with the appropriate config.)
SPECIMENS: Registry[type[SpecimenBase]] = Registry("specimen")
SPECIMENS.register("baseline", BaselineSpecimen)
SPECIMENS.register("mcts", MCTSSpecimen)
SPECIMENS.register("react", ReActSpecimen)

__all__ = [
    "SPECIMENS",
    "BaselineSpecimen",
    "MCTSSpecimen",
    "ReActSpecimen",
    "Registry",
    "Specimen",
    "SpecimenBase",
]
