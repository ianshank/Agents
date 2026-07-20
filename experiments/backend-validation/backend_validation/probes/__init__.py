"""L1 probe implementations and shared evidence helpers.

``load_all()`` imports every probe module so ``@register`` side effects fire; preflight
then cross-validates the registered ids against PROBES.yaml in BOTH directions.
"""

from __future__ import annotations

import importlib

_PROBE_MODULES = (
    "backend_validation.controls.synthetic",
    "backend_validation.probes.l1_tracing",
    "backend_validation.probes.l1_prompts",
    "backend_validation.probes.l1_datasets",
    "backend_validation.probes.l1_judge",
    "backend_validation.probes.l1_experiments",
    "backend_validation.probes.l1_policy",
)


def load_all() -> None:
    for module in _PROBE_MODULES:
        importlib.import_module(module)


def structured(excerpt: str) -> bool:
    """Evidence heuristic: a 2xx response whose body looks machine-readable (JSON-ish).

    Deliberately conservative and centralized so every probe means the same thing by
    "machine readable"; the excerpt format is ``HTTP <code>: <body>`` from the clients.
    """
    return excerpt.startswith("HTTP 2") and ("{" in excerpt or "[" in excerpt)


def parsed_score_in_unit_range(excerpt: str) -> bool:
    """True iff the excerpt carries an explicit ``score=<float>`` within [0, 1]."""
    for token in excerpt.replace(",", " ").split():
        if token.startswith("score="):
            try:
                value = float(token.removeprefix("score="))
            except ValueError:
                return False
            return 0.0 <= value <= 1.0
    return False
